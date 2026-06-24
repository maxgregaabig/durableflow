import pytest
from unittest.mock import MagicMock
from src.store import PostgresWorkflowStore, PostgresRowWrapper, PostgresCursorWrapper


def test_postgres_row_wrapper_indexing():
    # Test column indexing and name mapping
    desc = [("workflow_id",), ("status",), ("current_step",)]
    row_tuple = ("wf-123", "running", 2)
    wrapper = PostgresRowWrapper(row_tuple, desc)

    assert wrapper[0] == "wf-123"
    assert wrapper[1] == "running"
    assert wrapper[2] == 2
    assert wrapper["workflow_id"] == "wf-123"
    assert wrapper["status"] == "running"
    assert wrapper["current_step"] == 2
    assert len(wrapper) == 3
    assert list(wrapper) == ["wf-123", "running", 2]
    assert wrapper.keys() == ["workflow_id", "status", "current_step"]
    assert dict(wrapper) == {
        "workflow_id": "wf-123",
        "status": "running",
        "current_step": 2,
    }

    with pytest.raises(KeyError):
        _ = wrapper["non_existent"]


def test_postgres_connection_wrapper_parameter_replacement():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    from src.store import PostgresConnectionWrapper
    conn_wrapper = PostgresConnectionWrapper(mock_conn)

    # Execute a query with sqlite-style placeholders
    query = "SELECT * FROM workflows WHERE workflow_id = ? AND status = ?"
    params = ("wf-123", "completed")
    conn_wrapper.execute(query, params)

    # Verify that the placeholder was replaced with %s
    expected_query = "SELECT * FROM workflows WHERE workflow_id = %s AND status = %s"
    mock_cursor.execute.assert_called_once_with(expected_query, params)


def test_postgres_store_initialization():
    # Verify PostgresWorkflowStore can instantiate and execute DDL script
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    class TestPostgresWorkflowStore(PostgresWorkflowStore):
        def connect(self):
            from src.store import PostgresConnectionWrapper
            return PostgresConnectionWrapper(mock_conn)

    store = TestPostgresWorkflowStore("postgresql://localhost/db")
    
    # Verify that DDL was executed
    assert mock_cursor.execute.call_count >= 1
    # Verify table name workflows exists in the script execution
    last_call = mock_cursor.execute.call_args[0][0]
    assert "workflows" in last_call
    assert "step_results" in last_call
