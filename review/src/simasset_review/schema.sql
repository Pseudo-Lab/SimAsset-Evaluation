CREATE SCHEMA IF NOT EXISTS review;
SET search_path TO review, public;

CREATE TABLE IF NOT EXISTS assets (
 asset_id uuid PRIMARY KEY, source_namespace text NOT NULL, source_object_id text NOT NULL,
 display_name text NOT NULL, UNIQUE(source_namespace, source_object_id)
);
CREATE TABLE IF NOT EXISTS asset_variants (
 variant_id uuid PRIMARY KEY, asset_id uuid NOT NULL REFERENCES assets,
 content_hash text NOT NULL, physics_json jsonb NOT NULL DEFAULT '{}',
 provenance_json jsonb NOT NULL DEFAULT '{}', UNIQUE(asset_id, content_hash)
);
CREATE TABLE IF NOT EXISTS test_protocols (
 protocol_id uuid PRIMARY KEY, test_type text NOT NULL, protocol_version text NOT NULL,
 metric_rules jsonb NOT NULL, UNIQUE(test_type, protocol_version)
);
CREATE TABLE IF NOT EXISTS test_cases (
 case_id uuid PRIMARY KEY, variant_id uuid NOT NULL REFERENCES asset_variants,
 protocol_id uuid NOT NULL REFERENCES test_protocols, config_sha256 text NOT NULL,
 config jsonb NOT NULL, UNIQUE(variant_id, protocol_id, config_sha256)
);
CREATE TABLE IF NOT EXISTS test_runs (
 run_id uuid PRIMARY KEY, case_id uuid NOT NULL REFERENCES test_cases,
 source_namespace text NOT NULL, source_run_id text NOT NULL,
 bundle_sha256 text NOT NULL, origin text NOT NULL CHECK(origin IN ('team_shared','local_reproduction','fixture')),
 seed bigint NOT NULL, repeat_index integer,
 simulator text NOT NULL, engine_version text NOT NULL,
 harness_commit text, execution_status text NOT NULL CHECK(execution_status IN ('completed','error','skipped')),
 source_status text NOT NULL, status_reason text, raw_meta jsonb NOT NULL,
 source_manifest jsonb NOT NULL, warnings jsonb NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(source_namespace, source_run_id)
);
CREATE TABLE IF NOT EXISTS metric_definitions (
 metric_id uuid PRIMARY KEY, protocol_id uuid NOT NULL REFERENCES test_protocols,
 metric_name text NOT NULL, unit text NOT NULL, calculation_version text NOT NULL,
 UNIQUE(protocol_id, metric_name, calculation_version)
);
CREATE TABLE IF NOT EXISTS run_metrics (
 run_id uuid NOT NULL REFERENCES test_runs, metric_id uuid NOT NULL REFERENCES metric_definitions,
 metric_value double precision, metric_text text, valid boolean NOT NULL,
 invalid_reason text, raw_value text NOT NULL, raw_unit text NOT NULL,
 PRIMARY KEY(run_id, metric_id),
 CHECK(NOT (metric_value IS NOT NULL AND metric_text IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS run_artifacts (
 artifact_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES test_runs,
 artifact_type text NOT NULL, filename text NOT NULL, storage_uri text NOT NULL,
 sha256 text NOT NULL, size_bytes bigint NOT NULL, mime_type text NOT NULL,
 UNIQUE(run_id, filename)
);
CREATE TABLE IF NOT EXISTS run_judgments (
 judgment_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES test_runs,
 outcome text NOT NULL CHECK(outcome IN ('pass','fail','inconclusive')),
 reviewer text NOT NULL, criterion_key text NOT NULL, protocol_version text NOT NULL,
 rationale text NOT NULL, evidence_ids jsonb NOT NULL,
 supersedes_judgment_id uuid UNIQUE REFERENCES run_judgments,
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS import_attempts (
 attempt_id uuid PRIMARY KEY, source_path text NOT NULL, source_namespace text NOT NULL,
 bundle_sha256 text, run_id uuid REFERENCES test_runs,
 status text NOT NULL CHECK(status IN ('imported','duplicate','conflict','invalid')),
 diagnostics jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS runs_case ON test_runs(case_id);
CREATE INDEX IF NOT EXISTS judgments_run ON run_judgments(run_id, reviewed_at);
CREATE INDEX IF NOT EXISTS attempts_time ON import_attempts(created_at DESC);

CREATE OR REPLACE FUNCTION review.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'review records are append-only'; END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['assets','asset_variants','test_protocols','test_cases','test_runs','metric_definitions','run_metrics','run_artifacts','run_judgments','import_attempts'] LOOP
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname=t||'_immutable' AND tgrelid=('review.'||t)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON review.%I FOR EACH ROW EXECUTE FUNCTION review.reject_mutation()',t||'_immutable',t);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE VIEW v_run_metrics AS
 SELECT r.run_id, a.display_name AS asset, av.content_hash AS asset_version,
 p.test_type, p.protocol_version, r.seed, r.source_status, r.execution_status, r.origin,
 d.metric_name, m.metric_value, m.metric_text, d.unit, m.valid, m.invalid_reason,
 r.imported_at
 FROM test_runs r JOIN test_cases c USING(case_id) JOIN asset_variants av USING(variant_id)
 JOIN assets a USING(asset_id) JOIN test_protocols p USING(protocol_id)
 JOIN run_metrics m USING(run_id) JOIN metric_definitions d USING(metric_id);
CREATE OR REPLACE VIEW v_current_judgments AS
 SELECT j.* FROM run_judgments j WHERE NOT EXISTS
 (SELECT 1 FROM run_judgments n WHERE n.supersedes_judgment_id=j.judgment_id);
CREATE OR REPLACE VIEW v_test_coverage AS
 SELECT a.display_name AS asset, p.test_type, r.origin, r.execution_status, r.source_status,
 count(*) AS run_count, count(DISTINCT r.seed) AS distinct_seeds,
 av.content_hash AS asset_version, a.source_namespace
 FROM test_runs r JOIN test_cases c USING(case_id) JOIN asset_variants av USING(variant_id)
 JOIN assets a USING(asset_id) JOIN test_protocols p USING(protocol_id)
 GROUP BY a.display_name,p.test_type,r.origin,r.execution_status,r.source_status,av.content_hash,a.source_namespace;
