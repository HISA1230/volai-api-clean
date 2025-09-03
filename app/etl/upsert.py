import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

def upsert(table, values: dict, key_cols: list[str], update_cols: list[str]):
    stmt = insert(table).values(**values)
    set_ = {c: stmt.excluded[c] for c in update_cols}
    return stmt.on_conflict_do_update(index_elements=key_cols, set_=set_)
