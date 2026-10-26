
import json
import sqlite3
import zlib

import pandas as pd


def read_observations(path, clauses=(), parameters=(), limit=None):
    query = 'SELECT payload FROM observations'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY window_end'
    params = list(parameters)
    if limit is not None:
        query += ' LIMIT ?'
        params.append(int(limit))
    frames = []
    with sqlite3.connect(path) as db:
        cursor = db.execute(query, params)
        while rows := cursor.fetchmany(512):
            frames.append(pd.DataFrame([json.loads(zlib.decompress(row[0]) if isinstance(row[0], bytes) else row[0])
                                        for row in rows]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
