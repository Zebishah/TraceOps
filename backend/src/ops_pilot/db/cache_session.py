"""Invalidate display snapshots after successful API, MCP, and worker transactions."""

import asyncio
from typing import Any, cast

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction
from sqlalchemy.orm import ORMExecuteState, Session, SessionTransaction

from ops_pilot.cache.dashboard import invalidate_dashboard_cache

_SCOPES = "dashboard_cache_scopes"


class DashboardSyncSession(Session):
    pass


@event.listens_for(DashboardSyncSession, "before_flush")
def collect_changes(session: Session, _context: Any, _instances: Any) -> None:
    for value in session.new | session.dirty | session.deleted:
        table = getattr(value, "__table__", None)
        if table is None:
            continue
        if "organization_id" in table.c:
            history = inspect(value).attrs.organization_id.history
            for previous in history.deleted:
                session.info.setdefault(_SCOPES, set()).add(str(previous))
            if history.has_changes() and not history.deleted and value not in session.new:
                session.info.setdefault(_SCOPES, set()).add("*")
            scope = value.__dict__.get("organization_id")
            session.info.setdefault(_SCOPES, set()).add(str(scope) if scope else "*")
        elif table.name == "organizations":
            scope = value.__dict__.get("id")
            session.info.setdefault(_SCOPES, set()).add(str(scope) if scope else "*")
        elif table.name == "users" and value in session.deleted:
            session.info.setdefault(_SCOPES, set()).add("*")


@event.listens_for(DashboardSyncSession, "do_orm_execute")
def collect_bulk_changes(state: ORMExecuteState) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        table = getattr(state.statement, "table", None)
        if table is not None and (
            "organization_id" in table.c or table.name in {"organizations", "users"}
        ):
            # Core/ORM bulk writes need not load a tenant object. A global rotation is conservative.
            state.session.info.setdefault(_SCOPES, set()).add("*")
    elif getattr(state.statement, "is_text", False):
        # Textual writes cannot be reliably mapped to a tenant. Read-only commits only miss cache.
        state.session.info.setdefault(_SCOPES, set()).add("*")


@event.listens_for(DashboardSyncSession, "after_soft_rollback")
def discard_rollback(session: Session, previous: SessionTransaction) -> None:
    if previous.parent is None:
        session.info.pop(_SCOPES, None)


class DashboardTransaction(AsyncSessionTransaction):
    async def commit(self) -> None:
        await super().commit()
        await cast(DashboardSession, self.session).invalidate_snapshots()

    async def __aexit__(self, type_: Any, value: Any, traceback: Any) -> None:
        await super().__aexit__(type_, value, traceback)
        if type_ is None:
            await cast(DashboardSession, self.session).invalidate_snapshots()


class DashboardSession(AsyncSession):
    sync_session_class = DashboardSyncSession

    async def invalidate_snapshots(self) -> None:
        # Savepoint commits must never invalidate data that is still uncommitted.
        if not self.in_transaction():
            scopes = self.sync_session.info.pop(_SCOPES, set())
            if scopes:
                await asyncio.shield(invalidate_dashboard_cache(scopes))

    async def commit(self) -> None:
        await super().commit()
        await self.invalidate_snapshots()

    def begin(self) -> DashboardTransaction:
        return DashboardTransaction(self)

    def begin_nested(self) -> DashboardTransaction:
        return DashboardTransaction(self, nested=True)
