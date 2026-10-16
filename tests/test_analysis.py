"""Unit tests for analysis tools (spending spikes, cashflow projection, and savings recommendations)."""

from datetime import datetime, timedelta
import json
import pandas as pd
import pytest

from src.config import ACCOUNT_PATH, TRANSACTIONS_PATH, BILLS_PATH, BUDGETS_PATH
from src.tools import (
    cashflow_projection,
    detect_spending_spikes,
    savings_recommendations,
)
import src.tools as tools_module


class TestAnalysisTools:
    """Test suite for financial analysis tools."""

    def test_detect_spending_spikes_flagged_and_unflagged(self):
        """6.1: detect_spending_spikes flags Dining in 2026-07 and Health in 2026-08, and not others."""
        # Compute independently using pandas
        df = pd.read_csv(TRANSACTIONS_PATH)
        df_exp = df[df["type"] == "expense"].copy()

        # July 2026 vs June 2026
        june_exp = df_exp[df_exp["date"].str.startswith("2026-06")].groupby("category")["amount"].sum()
        july_exp = df_exp[df_exp["date"].str.startswith("2026-07")].groupby("category")["amount"].sum()

        expected_spikes_jul = []
        for cat in sorted(set(june_exp.index).union(set(july_exp.index))):
            prev = float(june_exp.get(cat, 0.0))
            curr = float(july_exp.get(cat, 0.0))
            increase = curr - prev
            if prev > 0:
                pct = (increase / prev) * 100
                if pct > 50.0 and increase >= 50.0:
                    expected_spikes_jul.append(cat)
            elif curr >= 50.0:
                expected_spikes_jul.append(cat)

        assert expected_spikes_jul == ["Dining"]

        raw_jul = detect_spending_spikes("2026-07")
        data_jul = json.loads(raw_jul)
        assert "error" not in data_jul
        flagged_jul = [s["category"] for s in data_jul["spikes"]]
        assert flagged_jul == ["Dining"]

        dining_spike = data_jul["spikes"][0]
        assert dining_spike["previous_amount"] == 166.00
        assert dining_spike["current_amount"] == 510.00
        assert dining_spike["increase_amount"] == 344.00
        assert dining_spike["increase_percent"] == 207.2

        # Check other categories in July 2026 are not flagged
        all_july_cats = set(july_exp.index)
        for cat in all_july_cats:
            if cat != "Dining":
                assert cat not in flagged_jul

        # August 2026 vs July 2026
        aug_exp = df_exp[df_exp["date"].str.startswith("2026-08")].groupby("category")["amount"].sum()

        expected_spikes_aug = []
        for cat in sorted(set(july_exp.index).union(set(aug_exp.index))):
            prev = float(july_exp.get(cat, 0.0))
            curr = float(aug_exp.get(cat, 0.0))
            increase = curr - prev
            if prev > 0:
                pct = (increase / prev) * 100
                if pct > 50.0 and increase >= 50.0:
                    expected_spikes_aug.append(cat)
            elif curr >= 50.0:
                expected_spikes_aug.append(cat)

        assert expected_spikes_aug == ["Health"]

        raw_aug = detect_spending_spikes("2026-08")
        data_aug = json.loads(raw_aug)
        assert "error" not in data_aug
        flagged_aug = [s["category"] for s in data_aug["spikes"]]
        assert flagged_aug == ["Health"]

        health_spike = data_aug["spikes"][0]
        assert health_spike["previous_amount"] == 50.00
        assert health_spike["current_amount"] == 427.80
        assert health_spike["increase_amount"] == 377.80
        assert health_spike["increase_percent"] == 755.6

        # Check other categories in August 2026 are not flagged
        all_aug_cats = set(aug_exp.index)
        for cat in all_aug_cats:
            if cat != "Health":
                assert cat not in flagged_aug

    def test_detect_spending_spikes_no_previous_month(self):
        """6.2: detect_spending_spikes('2026-06') returns an error because there is no previous month."""
        raw_jun = detect_spending_spikes("2026-06")
        data_jun = json.loads(raw_jun)
        assert "error" in data_jun
        assert "previous month" in data_jun["error"].lower()

    def test_cashflow_projection_scenarios(self):
        """6.3: cashflow_projection starting balance and total bills for 2026-08-31 and 2026-07-15."""
        acc_data = json.loads(ACCOUNT_PATH.read_text(encoding="utf-8"))
        opening_balance = float(acc_data["opening_balance"])

        df_tx = pd.read_csv(TRANSACTIONS_PATH)
        df_bills = pd.read_csv(BILLS_PATH)

        # Helper to compute bills independently in window
        def compute_bills_in_window(as_of_dt, days):
            total = 0.0
            for offset in range(days + 1):
                cur_dt = as_of_dt + timedelta(days=offset)
                for _, b in df_bills.iterrows():
                    if int(b["due_day"]) == cur_dt.day:
                        total += float(b["amount"])
            return round(total, 2)

        # Scenario 1: today="2026-08-31"
        today_1 = "2026-08-31"
        dt_1 = datetime.strptime(today_1, "%Y-%m-%d")
        tx_1 = df_tx[df_tx["date"] <= today_1]
        income_1 = float(tx_1[tx_1["type"] == "income"]["amount"].sum())
        expense_1 = float(tx_1[tx_1["type"] == "expense"]["amount"].sum())
        expected_balance_1 = round(opening_balance + income_1 - expense_1, 2)
        expected_bills_1 = compute_bills_in_window(dt_1, 30)

        raw_res_1 = cashflow_projection(days_ahead=30, today=today_1)
        data_1 = json.loads(raw_res_1)
        assert "error" not in data_1
        assert data_1["simulated_starting_balance"] == expected_balance_1
        assert data_1["total_bills"] == expected_bills_1
        assert data_1["simulated_starting_balance"] == 7564.57
        assert data_1["total_bills"] == 1869.99
        assert "Daily spending uses all discretionary expenses in the period, including one-off costs such as the August medical charge. This makes the projection more conservative." in data_1["assumptions"]

        # Scenario 2: today="2026-07-15"
        today_2 = "2026-07-15"
        dt_2 = datetime.strptime(today_2, "%Y-%m-%d")
        tx_2 = df_tx[df_tx["date"] <= today_2]
        income_2 = float(tx_2[tx_2["type"] == "income"]["amount"].sum())
        expense_2 = float(tx_2[tx_2["type"] == "expense"]["amount"].sum())
        expected_balance_2 = round(opening_balance + income_2 - expense_2, 2)
        expected_bills_2 = compute_bills_in_window(dt_2, 30)

        raw_res_2 = cashflow_projection(days_ahead=30, today=today_2)
        data_2 = json.loads(raw_res_2)
        assert "error" not in data_2
        assert data_2["simulated_starting_balance"] == expected_balance_2
        assert data_2["total_bills"] == expected_bills_2
        assert data_2["simulated_starting_balance"] == 6751.49
        assert data_2["total_bills"] == 1869.99

    def test_savings_recommendations_august(self):
        """6.4: savings_recommendations('2026-08') includes Health, and total_potential_saving equals sum of items."""
        raw_res = savings_recommendations("2026-08")
        data = json.loads(raw_res)
        assert "error" not in data

        recommendations = data["recommendations"]
        health_recs = [r for r in recommendations if r.get("category") == "Health"]
        assert len(health_recs) == 1
        health_item = health_recs[0]
        assert health_item["saving_to_budget"] == 327.80
        assert health_item["saving_to_prior_month"] == 377.80
        assert health_item["potential_monthly_saving"] == 377.80
        assert health_item["suggested_action"] == "Bring Health back to last month’s $50.00 to save $377.80."

        computed_sum = round(sum(r["potential_monthly_saving"] for r in recommendations), 2)
        assert data["total_potential_saving"] == computed_sum
        assert data["disclaimer"] == "General suggestion, not professional financial advice."

    def test_tool_vs_pandas_side_by_side_comparison(self):
        """5: Compares each tool figure with a pandas figure side by side and prints the table."""
        # 1. July Dining Spike
        raw_jul_tool = json.loads(detect_spending_spikes("2026-07"))
        dining_spike_tool = raw_jul_tool["spikes"][0]
        tool_jul_spike = f"+${dining_spike_tool['increase_amount']:.2f} (+{dining_spike_tool['increase_percent']}%)"

        df_tx = pd.read_csv(TRANSACTIONS_PATH)
        df_exp = df_tx[df_tx["type"] == "expense"]
        june_dining = float(df_exp[(df_exp["month"] == "2026-06") & (df_exp["category"] == "Dining")]["amount"].sum())
        july_dining = float(df_exp[(df_exp["month"] == "2026-07") & (df_exp["category"] == "Dining")]["amount"].sum())
        diff_dining = round(july_dining - june_dining, 2)
        pct_dining = round((diff_dining / june_dining) * 100, 1)
        pandas_jul_spike = f"+${diff_dining:.2f} (+{pct_dining}%)"

        # 2. August Health Spike
        raw_aug_tool = json.loads(detect_spending_spikes("2026-08"))
        health_spike_tool = raw_aug_tool["spikes"][0]
        tool_aug_spike = f"+${health_spike_tool['increase_amount']:.2f} (+{health_spike_tool['increase_percent']}%)"

        jul_health = float(df_exp[(df_exp["month"] == "2026-07") & (df_exp["category"] == "Health")]["amount"].sum())
        aug_health = float(df_exp[(df_exp["month"] == "2026-08") & (df_exp["category"] == "Health")]["amount"].sum())
        diff_health = round(aug_health - jul_health, 2)
        pct_health = round((diff_health / jul_health) * 100, 1)
        pandas_aug_spike = f"+${diff_health:.2f} (+{pct_health}%)"

        # 3. Cashflow Figures (Starting balance, bill total, daily discretionary average)
        raw_cf_tool = json.loads(cashflow_projection(30, "2026-08-31"))
        tool_start_bal = f"${raw_cf_tool['simulated_starting_balance']:.2f}"
        tool_bills_total = f"${raw_cf_tool['total_bills']:.2f}"
        tool_daily_disc = f"${raw_cf_tool['avg_daily_discretionary_spend']:.2f}"

        # Pandas Ground Truths
        acc = json.loads(ACCOUNT_PATH.read_text(encoding="utf-8"))
        open_bal = float(acc["opening_balance"])
        inc_to_date = float(df_tx[df_tx["type"] == "income"]["amount"].sum())
        exp_to_date = float(df_tx[df_tx["type"] == "expense"]["amount"].sum())
        pandas_start_bal = f"${open_bal + inc_to_date - exp_to_date:.2f}"

        df_bills = pd.read_csv(BILLS_PATH)
        as_of = datetime.strptime("2026-08-31", "%Y-%m-%d")
        total_bills_30d = 0.0
        for offset in range(30 + 1):
            cur = as_of + timedelta(days=offset)
            matching = df_bills[df_bills["due_day"] == cur.day]
            for _, r in matching.iterrows():
                total_bills_30d += float(r["amount"])
        pandas_bills_total = f"${total_bills_30d:.2f}"

        bill_categories = set(df_bills["category"].dropna().unique())
        disc_expenses = df_exp[~df_exp["category"].isin(bill_categories)]["amount"].sum()
        total_days = (datetime(2026, 8, 31) - datetime(2026, 6, 1)).days + 1
        pandas_daily_disc = f"${disc_expenses / total_days:.2f}"

        # Build comparison table
        rows = [
            ("July Dining Spike (Increase)", tool_jul_spike, pandas_jul_spike, tool_jul_spike == pandas_jul_spike),
            ("August Health Spike (Increase)", tool_aug_spike, pandas_aug_spike, tool_aug_spike == pandas_aug_spike),
            ("Starting Balance (as of 08-31)", tool_start_bal, pandas_start_bal, tool_start_bal == pandas_start_bal),
            ("Total Bills (30-day window)", tool_bills_total, pandas_bills_total, tool_bills_total == pandas_bills_total),
            ("Daily Discretionary Average", tool_daily_disc, pandas_daily_disc, tool_daily_disc == pandas_daily_disc),
        ]

        print("\n" + "=" * 90)
        print(f"{'Metric':<35} | {'Tool Value':<20} | {'Pandas Value':<20} | {'Match'}")
        print("-" * 90)
        for metric, t_val, p_val, matched in rows:
            print(f"{metric:<35} | {t_val:<20} | {p_val:<20} | {matched}")
            assert matched is True
        print("=" * 90 + "\n")

        assert raw_cf_tool["simulated_starting_balance"] == 7564.57
        assert raw_cf_tool["total_bills"] == 1869.99
        assert raw_cf_tool["avg_daily_discretionary_spend"] == 36.14

    def test_cashflow_negative_balance_covers_all_bills_false(self, tmp_path, monkeypatch):
        """6.5: Temporary data folder that makes balance negative and checks covers_all_bills is false."""
        tmp_acc = tmp_path / "account.json"
        tmp_acc.write_text(
            json.dumps({"opening_balance": 10.00, "opening_date": "2026-05-31", "currency": "USD"}),
            encoding="utf-8",
        )

        tmp_tx = tmp_path / "transactions.csv"
        # Has one transaction so file is not considered empty
        tmp_tx.write_text(
            "date,month,description,category,type,amount\n2026-06-01,2026-06,Deposit,Other,income,0.00\n",
            encoding="utf-8",
        )

        tmp_bills = tmp_path / "bills.csv"
        # A large bill due in early September
        tmp_bills.write_text(
            "bill_name,due_day,amount,category\nApartment Rent,1,1500.00,Housing\n",
            encoding="utf-8",
        )

        tmp_budgets = tmp_path / "budgets.json"
        tmp_budgets.write_text(json.dumps({}), encoding="utf-8")

        monkeypatch.setattr(tools_module, "ACCOUNT_PATH", tmp_acc)
        monkeypatch.setattr(tools_module, "TRANSACTIONS_PATH", tmp_tx)
        monkeypatch.setattr(tools_module, "BILLS_PATH", tmp_bills)
        monkeypatch.setattr(tools_module, "BUDGETS_PATH", tmp_budgets)

        raw_res = cashflow_projection(days_ahead=30, today="2026-08-31")
        data = json.loads(raw_res)

        assert "error" not in data
        assert data["simulated_starting_balance"] == 10.00
        assert data["total_bills"] == 1500.00
        assert data["lowest_balance"] < 0
        assert data["covers_all_bills"] is False
