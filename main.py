import os
from datetime import datetime
from flask import Flask, request
from jira_client import JiraAPI, project_data_to_df, user_data_to_df, filter_df_by_date
import pandas as pd
from google.cloud import storage

app = Flask(__name__)

# 初始化 GCS 客戶端
storage_client = storage.Client()
# BUCKET_NAME = "temp-report"
BUCKET_NAME = os.environ.get("BUCKET_NAME", "temp-report")  # 預設值可保留

# 設定參數
DOMAIN = "https://nl-pmis.atlassian.net"
START_DATE = "2025-09-01"
END_DATE = "2025-10-01"

GROUPS = {
    "Executive Unit": ["AWS-TW", "AWS-HK", "GCP-TW", "GWS-TW", "Google-HK", "Data", "Multicloud", "MS", "PMO", "專案開發部", "SEA", "產品及解決方案處"],
    "Job Level": ["TWO1", "TWO2", "TWO3", "HKO1"],
    "Job Title": ["SA", "PM", "Data Engineer", "SRE", "TAM"]
}


@app.route("/", methods=["GET"])
def generate_report():
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_TOKEN")

    if not email or not token:
        return "Missing JIRA_EMAIL or JIRA_TOKEN environment variables.", 500

    jira = JiraAPI(DOMAIN, email, token, GROUPS)

    # Step 1: 取得 issues
    issues = jira.get_active_issues(START_DATE, END_DATE)
    print(f"[INFO] 總共取得 {len(issues)} 筆 active issues")

    # Step 2: issues 轉成 projects 結構
    projects = jira.trace_project_info_by_issues(issues)
    print(f"[INFO] 對應到 {len(projects)} 個 project")

    # Step 3: 抓取每個 issue 的 worklogs 與 user info
    user_data = {}
    for project in projects:
        for issue in project["issues"]:
            issue["worklogs"] = jira.get_worklog_from_issue_id(issue["key"])
            for worklog in issue["worklogs"]:
                user_id = worklog.get("owner_id")
                if user_id and user_id not in user_data:
                    user_data[user_id] = jira.get_user_group_info_from_user_id(user_id)

    # Step 4: 轉換為 DataFrame 並合併
    df = project_data_to_df(projects)
    user_df = user_data_to_df(user_data)
    df = pd.merge(df, user_df, on="worklog_owner_id", how="left")
    print(f"[INFO] 最終資料筆數（含 worklogs）：{len(df)}")

    # Step 5: 時間篩選
    start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    end = datetime.strptime(END_DATE, "%Y-%m-%d").date()
    filtered_df = filter_df_by_date(df, start, end)
    print(f"[INFO] 過濾後筆數：{len(filtered_df)}")

    # Step 6: 輸出至 GCS
    filename = f"jiraReport_{START_DATE}_{END_DATE}.csv"
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(filtered_df.to_csv(index=False), content_type="text/csv")

    print(f"[SUCCESS] 上傳完成 gs://{BUCKET_NAME}/{filename}")
    return f"✅ 報表已產出並上傳至 gs://{BUCKET_NAME}/{filename}\n筆數：{len(filtered_df)}", 200

# if __name__ == "__main__":
#     app.run(debug=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Cloud Run 會提供 $PORT 環境變數
    app.run(host="0.0.0.0", port=port)
