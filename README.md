# Jira Report Exporter (Cloud Run Function)

這是一個用 Python + Flask 製作的 Jira 月報自動匯出工具，部署在 GCP Cloud Run。  
系統會連接 Jira API，自動擷取指定時間範圍內的 worklog 資料並匯出報表（CSV），儲存到 GCS Bucket 中。

---

## 如何部署到 Cloud Run

### 1. 先準備好環境變數（在部署時設定）

| 變數名稱        | 說明                           |
|------------------|--------------------------------|
| `JIRA_DOMAIN`     | Jira 網域，例如 `https://your-domain.atlassian.net` |
| `JIRA_EMAIL`      | 你的 Jira 登入帳號 email      |
| `JIRA_TOKEN`      | Jira 的 API Token（[產生位置](https://id.atlassian.com/manage-profile/security/api-tokens)） |
| `GCS_BUCKET`      | 用來儲存報表的 Cloud Storage bucket 名稱 |

> 📌 **記得：Cloud Run 的服務帳號（Service Account）要有存取 GCS 權限**
建議角色為：
- `roles/storage.objectCreator`
- `roles/storage.objectViewer`  
我最後改用Admin

---

### 2. GitHub 設定部署（使用 Buildpacks）

建議使用 Buildpacks 部署方式（不需 Dockerfile）：

| 欄位                     | 設定值         |
|--------------------------|----------------|
| Build context directory  | `/`            |
| Entrypoint               | 留空 ✅         |
| Function target          | 留空 ✅         |

⚠️**Function target 不可填寫！** 因為這是 Web Server 不是 Function handler

---

## 呼叫方式（HTTP API）

Cloud Run 部署完成後，你可以透過以下方式呼叫 API：

### 🔸 POST `/`

```bash
curl -v -H "Authorization: Bearer $(gcloud auth print-identity-token)"   "https://jira-report-test-1075612823060.asia-east1.run.app?start=2025-08-10&end=2025-08-20"
```
