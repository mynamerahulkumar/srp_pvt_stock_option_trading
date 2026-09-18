from __future__ import annotations

import pytest

from trading.dhan_client import DhanClientError, extract_ltp, extract_order_id, format_dhan_error, unwrap_sdk


def test_extract_ltp_from_documented_shape():
    response = {"status": "success", "data": {"NSE_EQ": {"1333": {"last_price": 704.95}}}}
    assert extract_ltp(response, "1333") == pytest.approx(704.95)


def test_extract_ltp_from_nested_data_data():
    response = {"status": "success", "data": {"data": {"NSE_EQ": {"1333": {"last_price": 705.1}}}}}
    assert extract_ltp(response, "1333") == pytest.approx(705.1)


def test_extract_order_id_from_place_response():
    result = {"response": {"status": "success", "data": {"orderId": "112233"}}}
    assert extract_order_id(result) == "112233"


def test_unwrap_empty_failure_is_readable():
    response = {
        "status": "failure",
        "remarks": {"error_code": None, "error_type": None, "error_message": None},
        "data": "",
    }
    with pytest.raises(DhanClientError, match="static IP"):
        unwrap_sdk(response)


def test_format_dhan_error_with_code():
    message = format_dhan_error(
        {"status": "failure", "remarks": {"error_code": "DH-911", "error_message": "Invalid IP"}}
    )
    assert "DH-911" in message
    assert "Invalid IP" in message
