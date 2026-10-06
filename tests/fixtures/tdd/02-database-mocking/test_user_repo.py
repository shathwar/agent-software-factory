from unittest.mock import patch
import pytest

def test_get_user_by_id_mocked_db():
    with patch("psycopg2.connect") as mock_conn:
        mock_cursor = mock_conn.return_value.cursor.return_value
        mock_cursor.fetchone.return_value = (1, "alice@example.com")
        
        user = get_user_by_id(1)
        assert user.email == "alice@example.com"
