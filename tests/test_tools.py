"""Unit tests for read-only financial tools in src/tools.py."""

import json
import pytest

from src.tools import (
    get_monthly_summary,
    spending_by_category,
    get_transactions,
    upcoming_bills,
    budget_status,
    find_possible_duplicates,
    TOOL_SCHEMAS,
    TOOLS_BY_NAME,
)


class TestFinancialTools:
    """Test suite verifying each tool meets required criteria and data expectations."""

    def test_get_monthly_summary(self):
        """Test monthly summary calculations for income, expenses, and savings rate."""
        # July 2026 test
        raw_res = get_monthly_summary("2026-07")
        data = json.loads(raw_res)

        assert "error" not in data
        assert data["month"] == "2026-07"
        assert data["total_income"] == 4500.00
        assert data["total_expenses"] == 3086.46
        assert data["net_savings"] == 1413.54
        assert data["savings_rate"] == 31.4

        # Non-existent month test
        raw_err = get_monthly_summary("2026-05")
        err_data = json.loads(raw_err)
        assert "error" in err_data
        assert "2026-05" in err_data["error"]

    def test_spending_by_category(self):
        """Test spending by category, sorting, and specific expected data values."""
        # July 2026: Dining spending must be 510.00
        raw_jul = spending_by_category("2026-07")
        data_jul = json.loads(raw_jul)
        assert "error" not in data_jul
        spending_jul = data_jul["spending_by_category"]
        assert spending_jul["Dining"] == 510.00

        # Verify sorted largest first
        amounts = list(spending_jul.values())
        assert amounts == sorted(amounts, reverse=True)

        # August 2026: Health spending must be 427.80
        raw_aug = spending_by_category("2026-08")
        data_aug = json.loads(raw_aug)
        assert "error" not in data_aug
        spending_aug = data_aug["spending_by_category"]
        assert spending_aug["Health"] == 427.80

        # Non-existent month error handling
        raw_err = spending_by_category("2026-01")
        err_data = json.loads(raw_err)
        assert "error" in err_data

    def test_get_transactions(self):
        """Test retrieving transactions unfiltered and filtered by category."""
        # Unfiltered July
        raw_all = get_transactions("2026-07")
        data_all = json.loads(raw_all)
        assert "error" not in data_all
        assert data_all["count"] > 0
        assert len(data_all["transactions"]) == data_all["count"]

        # Filtered by Dining category
        raw_dining = get_transactions("2026-07", "Dining")
        data_dining = json.loads(raw_dining)
        assert "error" not in data_dining
        assert data_dining["count"] == 10
        for tx in data_dining["transactions"]:
            assert tx["category"] == "Dining"

        # Non-existent category
        raw_none = get_transactions("2026-07", "UnknownCategory")
        data_none = json.loads(raw_none)
        assert "error" in data_none

    def test_upcoming_bills(self):
        """Test bill retrieval within specified days from a reference date."""
        # 30 days from 2026-07-01 should capture all 6 monthly bills
        raw_res = upcoming_bills("2026-07-01", 30)
        data = json.loads(raw_res)
        assert "error" not in data
        assert data["count"] == 6

        bill_names = [b["bill_name"] for b in data["upcoming_bills"]]
        assert "Apartment Rent" in bill_names
        assert "Health & Auto Insurance" in bill_names
        assert "Streaming Bundle" in bill_names
        assert "Electric Utility" in bill_names
        assert "Fiber Internet" in bill_names
        assert "Mobile Phone Plan" in bill_names

        # Short window: 7 days from 2026-07-01 should only capture Rent (day 1) and Insurance (day 5)
        raw_short = upcoming_bills("2026-07-01", 7)
        data_short = json.loads(raw_short)
        assert data_short["count"] == 2

        # Invalid date handling
        raw_invalid = upcoming_bills("invalid-date")
        data_invalid = json.loads(raw_invalid)
        assert "error" in data_invalid

    def test_upcoming_bills_total_due(self):
        """Test upcoming_bills computes bill_count and total_due accurately."""
        import pandas as pd
        from src.config import BILLS_PATH

        raw_res = upcoming_bills("2026-10-16", 30)
        data = json.loads(raw_res)
        assert "error" not in data
        assert data["bill_count"] == 6
        assert data["total_due"] == 1869.99

        bills_df = pd.read_csv(BILLS_PATH)
        expected_total = round(float(bills_df["amount"].sum()), 2)
        assert data["total_due"] == expected_total

    def test_budget_status(self):
        """Test budget limits, actual spending, percent used, and over-budget flags."""
        raw_res = budget_status("2026-07")
        data = json.loads(raw_res)
        assert "error" not in data

        categories = data["categories"]
        dining_status = categories["Dining"]
        assert dining_status["limit"] == 300.00
        assert dining_status["spent"] == 510.00
        assert dining_status["percent_used"] == 170.0
        assert dining_status["is_over_budget"] is True
        assert "over_budget" not in dining_status
        assert "Dining" in data["over_budget_categories"]

        # August Health over budget check
        raw_aug = budget_status("2026-08")
        data_aug = json.loads(raw_aug)
        health_status = data_aug["categories"]["Health"]
        assert health_status["limit"] == 100.00
        assert health_status["spent"] == 427.80
        assert health_status["percent_used"] == 427.8
        assert health_status["is_over_budget"] is True
        assert "over_budget" not in health_status
        assert "Health" in data_aug["over_budget_categories"]

    def test_find_possible_duplicates(self):
        """Test finding exact duplicate transactions for audit."""
        # July 2026 has the known duplicate Blue Bottle Coffee charge on 2026-07-14
        raw_jul = find_possible_duplicates("2026-07")
        data_jul = json.loads(raw_jul)
        assert "error" not in data_jul
        assert data_jul["count"] == 1

        dup_group = data_jul["duplicate_groups"][0]
        assert dup_group["date"] == "2026-07-14"
        assert dup_group["description"] == "Blue Bottle Coffee Order #8841"
        assert dup_group["amount"] == 16.75
        assert dup_group["count"] == 2
        assert len(dup_group["transactions"]) == 2

        # June 2026 has no duplicate transactions
        raw_jun = find_possible_duplicates("2026-06")
        data_jun = json.loads(raw_jun)
        assert "error" not in data_jun
        assert data_jun["count"] == 0
        assert data_jun["duplicate_groups"] == []

    def test_tool_schemas(self):
        """Verify that all JSON schemas are properly formatted and registered."""
        assert len(TOOL_SCHEMAS) == 7
        assert len(TOOLS_BY_NAME) == 8

        for schema in TOOL_SCHEMAS:
            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema
            assert schema["parameters"]["type"] == "object"
            assert "properties" in schema["parameters"]
            assert schema["name"] in TOOLS_BY_NAME
