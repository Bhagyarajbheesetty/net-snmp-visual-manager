from snmp.client import SNMPClient, DeviceConfig, VarBind, MIBLoader
import asyncio
from typing import List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WalkSession:
    id: str
    device_id: int
    oid_from: str
    oid_to: Optional[str]
    status: str
    results: List[VarBind] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    progress_callback: Optional[Callable[[List[VarBind]], Awaitable[None]]] = None


class WalkEngine:
    def __init__(self, mib_loader: Optional[MIBLoader] = None):
        self.sessions: dict = {}
        self.mib_loader = mib_loader

    async def start_walk(
        self,
        session_id: str,
        device_config: DeviceConfig,
        oid_from: str,
        oid_to: Optional[str] = None,
        use_bulk: bool = True,
        progress_callback: Optional[Callable[[List[VarBind]], Awaitable[None]]] = None,
    ) -> WalkSession:
        stop_event = asyncio.Event()
        session = WalkSession(
            id=session_id,
            device_id=0,
            oid_from=oid_from,
            oid_to=oid_to,
            status="running",
            stop_event=stop_event,
            progress_callback=progress_callback,
        )
        self.sessions[session_id] = session

        asyncio.create_task(self._run_walk(session, device_config, use_bulk))
        return session

    async def _run_walk(self, session: WalkSession, device_config: DeviceConfig, use_bulk: bool):
        client = SNMPClient(device_config, mib_loader=self.mib_loader)
        try:
            # Gather expected MIB objects under session.oid_from
            from snmp.mib import mib_manager
            expected_objs = [
                o for o in mib_manager.search_objects()
                if client._is_sub_tree(o.oid, session.oid_from) and not o.is_table
            ]
            expected_map = {o.oid: o for o in expected_objs}
            tracked_expected_oids = sorted(
                expected_map.keys(),
                key=lambda x: [int(p) for p in x.split(".") if p.isdigit()]
            )

            current_expected_idx = 0
            checked_failed_oids = set()
            seq_counter = 0

            async def _on_batch_with_gaps(batch):
                nonlocal current_expected_idx, seq_counter
                # Check for any expected MIB objects that were skipped before batch items
                for vb in batch:
                    # If vb is already a failed item emitted by client walk, assign seq and record it
                    if getattr(vb, "status", "ok") != "ok":
                        seq_counter += 1
                        vb.seq = seq_counter
                        checked_failed_oids.add(vb.oid)
                        session.results.append(vb)
                        while current_expected_idx < len(tracked_expected_oids):
                            if client._oid_compare(tracked_expected_oids[current_expected_idx], vb.oid) <= 0:
                                current_expected_idx += 1
                            else:
                                break
                        continue

                    # Look for expected OIDs that are lexicographically strictly before vb.oid
                    while current_expected_idx < len(tracked_expected_oids):
                        exp_oid = tracked_expected_oids[current_expected_idx]
                        cmp_res = client._oid_compare(exp_oid, vb.oid)
                        if cmp_res < 0:
                            # exp_oid was skipped by device
                            if exp_oid not in checked_failed_oids and not vb.oid.startswith(exp_oid + "."):
                                checked_failed_oids.add(exp_oid)
                                exp_info = expected_map.get(exp_oid)
                                exp_name = exp_info.name if exp_info else exp_oid
                                seq_counter += 1
                                failed_vb = VarBind(
                                    oid=exp_oid,
                                    name=exp_name,
                                    type="UNANSWERED",
                                    value="No response from agent",
                                    index="",
                                    status="failed",
                                    error_msg="Object not implemented by device",
                                    seq=seq_counter,
                                )
                                session.results.append(failed_vb)
                                if session.progress_callback:
                                    await session.progress_callback([failed_vb])
                            current_expected_idx += 1
                        elif cmp_res == 0 or vb.oid.startswith(exp_oid + "."):
                            # Matched scalar or column instance
                            checked_failed_oids.add(exp_oid)
                            current_expected_idx += 1
                            break
                        else:
                            break

                    seq_counter += 1
                    vb.seq = seq_counter
                    checked_failed_oids.add(vb.oid)
                    session.results.append(vb)
                    if session.progress_callback:
                        await session.progress_callback([vb])

            if use_bulk and device_config.version in ("v2c", "v3"):
                await client.bulk_walk(
                    session.oid_from,
                    session.oid_to,
                    progress_callback=_on_batch_with_gaps,
                    stop_event=session.stop_event,
                    expected_oids=tracked_expected_oids,
                )
            else:
                await client.walk(
                    session.oid_from,
                    session.oid_to,
                    progress_callback=_on_batch_with_gaps,
                    stop_event=session.stop_event,
                    expected_oids=tracked_expected_oids,
                )

            # Check if any remaining expected MIB objects at the end of the subtree were never reached
            while current_expected_idx < len(tracked_expected_oids):
                exp_oid = tracked_expected_oids[current_expected_idx]
                if exp_oid not in checked_failed_oids:
                    checked_failed_oids.add(exp_oid)
                    exp_info = expected_map.get(exp_oid)
                    exp_name = exp_info.name if exp_info else exp_oid
                    seq_counter += 1
                    failed_vb = VarBind(
                        oid=exp_oid,
                        name=exp_name,
                        type="UNANSWERED",
                        value="No response from agent",
                        index="",
                        status="failed",
                        error_msg="Object not implemented by device",
                        seq=seq_counter,
                    )
                    session.results.append(failed_vb)
                    if session.progress_callback:
                        await session.progress_callback([failed_vb])
                current_expected_idx += 1

            session.status = "stopped" if session.stop_event.is_set() else "completed"
        except Exception as e:
            session.status = "error"
            session.error = str(e)
        finally:
            session.completed_at = datetime.now()
            if hasattr(session, "history_id") and session.history_id:
                try:
                    from database import get_connection
                    conn = get_connection()
                    conn.execute(
                        "UPDATE query_history SET status = ?, result_count = ?, completed_at = ?, error_message = ? WHERE id = ?",
                        (session.status, len(session.results), session.completed_at, session.error, session.history_id)
                    )
                    conn.commit()
                except Exception:
                    pass

    def stop_walk(self, session_id: str) -> bool:
        if session_id in self.sessions:
            self.sessions[session_id].stop_event.set()
            self.sessions[session_id].status = "stopped"
            return True
        return False

    def stop_all(self) -> int:
        count = 0
        for s in self.sessions.values():
            if s.status == "running":
                s.stop_event.set()
                s.status = "stopped"
                count += 1
        return count

    def get_session(self, session_id: str) -> Optional[WalkSession]:
        return self.sessions.get(session_id)

    def get_results(self, session_id: str) -> List[VarBind]:
        session = self.sessions.get(session_id)
        return session.results if session else []


walk_engine = WalkEngine()