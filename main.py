import os
import traceback
from datetime import datetime
from flask import Flask, request
from jira_client import JiraAPI, project_data_to_df, user_data_to_df, filter_df_by_date
import pandas as pd
from google.cloud import storage
from datetime import datetime

app = Flask(__name__)

storage_client = storage.Client()
BUCKET_NAME = os.environ.get("BUCKET_NAME", "temp-report")
DOMAIN = "https://nl-pmis.atlassian.net"

GROUPS = {
    "Executive Unit": ["AWS-TW", "AWS-HK", "GCP-TW", "GWS-TW", "Google-HK", "Data", "Multicloud", "MS", "PMO", "專案開發部", "SEA", "產品及解決方案處"],
    "Job Level": ["TWO1", "TWO2", "TWO3", "HKO1"],
    "Job Title": ["SA", "PM", "Data Engineer", "SRE", "TAM"]
}


@app.route("/", methods=["GET"])
def generate_report():
    try:
        #  Step 0: 確認認證參數
        email = os.environ.get("JIRA_EMAIL")
        token = os.environ.get("JIRA_TOKEN")
        if not email or not token:
            return "Missing JIRA_EMAIL or JIRA_TOKEN environment variables.", 500

        #  Step 0-1: 取得 URL 傳入的日期參數
        start_str = request.args.get("start")
        end_str = request.args.get("end")
        if not start_str or not end_str:
            return "❌ 請提供 start 與 end query 參數，例如 ?start=2025-09-01&end=2025-10-01", 400

        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        print(f"[INFO] 解析日期成功：start={start_date}, end={end_date}")

        # Step 1: 初始化 Jira API
        jira = JiraAPI(DOMAIN, email, token, GROUPS)

        # Step 2: 抓取 active issues
        issues = jira.get_active_issues(start_str, end_str)
        print(f"[INFO] 總共取得 {len(issues)} 筆 active issues")

        # Step 3: 轉換成 project 結構
        projects = jira.trace_project_info_by_issues(issues)
        print(f"[INFO] 對應到 {len(projects)} 個 project")

        # Step 4: 補上每個 issue 的 worklog 與 user 群組
        user_data = {}
        for project in projects:
            for issue in project["issues"]:
                issue["worklogs"] = jira.get_worklog_from_issue_id(issue["key"])
                for worklog in issue["worklogs"]:
                    user_id = worklog.get("owner_id")
                    if user_id and user_id not in user_data:
                        user_data[user_id] = jira.get_user_group_info_from_user_id(user_id)
        print(f"[INFO] 共補上 user 資料：{len(user_data)} 位")

        # Step 5: 組成 DataFrame
        df = project_data_to_df(projects)
        user_df = user_data_to_df(user_data)
        df = pd.merge(df, user_df, on="worklog_owner_id", how="left")
        print(f"[INFO] 合併後筆數（含 worklogs）：{len(df)}")

        # Step 6: 過濾時間範圍
        filtered_df = filter_df_by_date(df, start_date, end_date)
        print(f"[INFO] 過濾後筆數：{len(filtered_df)}")

        # Step 7: 上傳到 GCS
        # filename = f"jiraReport_{start_str}_{end_str}.csv"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M")
        filename = f"jiraReport_{timestamp}.csv"
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(filtered_df.to_csv(index=False, encoding="utf-8-sig"), content_type="text/csv")
        print(f"[SUCCESS] 上傳完成 gs://{BUCKET_NAME}/{filename}")

        return f" 報表已產出並上傳至 gs://{BUCKET_NAME}/{filename}\n筆數：{len(filtered_df)}", 200

    except Exception as e:
        print("[ERROR] 發生例外錯誤：")
        traceback.print_exc()
        return f"❌ 發生錯誤：{str(e)}", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
