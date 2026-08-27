"""
tests/test_instances.py - Regression tests for app/instances.py.

Covers edge cases that the fixture-based tests skip because they mock out
get_instances() / get_active().
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.instances import OsduInstance, _load_instances, get_instances


class TestNoInstancesFallback:
    """When no INSTANCE_* env vars are set, _load_instances must not crash."""

    def test_dummy_none_instance_created(self):
        """Regression: the 'none' dummy must supply data_partition_id."""
        import app.instances as mod

        # Save original module state
        orig_instances = dict(mod._instances)
        orig_active = mod._active_instance_name

        try:
            # Clear all state so _load_instances runs from scratch
            mod._instances.clear()
            mod._active_instance_name = ""

            # Run with no INSTANCE_* env vars at all
            clean_env = {k: v for k, v in os.environ.items()
                         if not k.startswith("INSTANCE_")}
            # Also remove legacy env vars that could create a legacy instance
            for key in ("OSDU_HOST", "OSDU_BASE_URL", "CLIENT_ID", "TENANT",
                        "REFRESH_TOKEN", "AZURE_TENANT_ID"):
                clean_env.pop(key, None)

            with patch.dict(os.environ, clean_env, clear=True):
                _load_instances()

            # Should have created a "none" dummy instead of crashing
            assert "none" in mod._instances
            none_inst = mod._instances["none"]
            assert isinstance(none_inst, OsduInstance)
            assert none_inst.data_partition_id == ""
            assert none_inst.hostname == ""
            assert mod._active_instance_name == "none"

        finally:
            # Restore
            mod._instances.clear()
            mod._instances.update(orig_instances)
            mod._active_instance_name = orig_active

    def test_osdu_instance_defaults_config_fields(self):
        """hostname and data_partition_id should default to empty string."""
        inst = OsduInstance(name="minimal")
        assert inst.hostname == ""
        assert inst.data_partition_id == ""
        assert inst.tenant_id == ""
        assert inst.graphql_pg_conn_string == ""

    def test_per_instance_pg_conn_string(self):
        """graphql_pg_conn_string field is stored per-instance."""
        interop = OsduInstance(name="interop", graphql_pg_conn_string="host=pg.eqn dbname=rddms")
        preship = OsduInstance(name="preship")  # no PG configured
        assert interop.graphql_pg_conn_string == "host=pg.eqn dbname=rddms"
        assert preship.graphql_pg_conn_string == ""
