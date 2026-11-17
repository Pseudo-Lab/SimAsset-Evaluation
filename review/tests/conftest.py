import csv
import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from simasset_review.bundle import FIELDS, TS_FIELDS, TS_UNITS
from simasset_review.db import Settings, initialize


@pytest.fixture(scope='session')
def database(tmp_path_factory):
    main = Settings.load()
    name = 'simasset_review_test_' + uuid4().hex[:12]
    # A fresh database owned by this test only; no DELETE/TRUNCATE on the prototype.
    with psycopg.connect(main.dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    settings = Settings(tmp_path_factory.mktemp('review-state'), make_conninfo(main.dsn, dbname=name))
    initialize(settings)
    try:
        yield settings
    finally:
        with psycopg.connect(main.dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture
def namespace():
    return 'test-' + uuid4().hex


@pytest.fixture
def bundle(tmp_path):
    p = tmp_path/'source'; p.mkdir()
    meta = {'run_id':'incline-cube-file-ramp45deg-s0','test':'incline',
            'condition':'ramp45deg','seed':0,'mujoco':'3.17.0','timestep':0.002,
            'timeseries_units':TS_UNITS,'asset':{'mass_kg':0.1},
            'perturb_cfg':{'tilt_deg':2,'pos_mm':1},'perturb':{'tilt_deg':0.3}}
    (p/'meta.json').write_text(json.dumps(meta))
    metrics = [('mass_kg','0.1','kg'),('peak_pen','1.25','mm'),('theta_tip_pred_deg','45','deg'),
               ('accel_err_pct','nan','%'),('motion_mode','sliding',''),('left_ramp','1','bool')]
    with (p/'summary.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(FIELDS)
        for metric,value,unit in metrics:
            writer.writerow([meta['run_id'],'cube','a'*64,'incline','file','ramp45deg',0,'ok',metric,value,unit])
    with (p/'timeseries.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(TS_FIELDS)
        for t,z,pen in [(0,100,0),(.002,99,1.25),(.004,98,0)]:
            writer.writerow([t,0,0,z,1,0,0,0,0,0,-1,0,0,0,1,pen])
    return p


def edit_csv(path, edit):
    with path.open(newline='') as f: rows=list(csv.DictReader(f))
    edit(rows)
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)


def edit_meta(path, edit):
    data=json.loads(path.read_text());edit(data);path.write_text(json.dumps(data))
