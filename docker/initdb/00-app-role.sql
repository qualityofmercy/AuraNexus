-- Local dev only: in GCP Terraform creates this login. The app role must never own tables or bypass RLS.
CREATE ROLE auranexus_app LOGIN PASSWORD 'app' NOSUPERUSER NOBYPASSRLS;
