# 🔧 Google Sheets 연동 설정 가이드

## 📋 개요

이 가이드는 TEAM FIRE 25 대시보드를 Google Sheets와 연동하여 포트폴리오 데이터를 저장/불러오는 방법을 설명합니다.

---

## 🚀 설정 단계

### 1단계: Google Cloud 프로젝트 생성

1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. 새 프로젝트 생성 (예: `fire25-dashboard`)
3. 프로젝트 선택

### 2단계: Google Sheets API 활성화

1. 좌측 메뉴 → **API 및 서비스** → **라이브러리**
2. 검색: `Google Sheets API` → **사용** 클릭
3. 검색: `Google Drive API` → **사용** 클릭

### 3단계: 서비스 계정 생성

1. 좌측 메뉴 → **API 및 서비스** → **사용자 인증 정보**
2. **+ 사용자 인증 정보 만들기** → **서비스 계정**
3. 서비스 계정 이름 입력 (예: `fire25-sheets`)
4. **완료** 클릭

### 4단계: 서비스 계정 키 생성

1. 생성된 서비스 계정 클릭
2. **키** 탭 → **키 추가** → **새 키 만들기**
3. **JSON** 선택 → **만들기**
4. JSON 파일이 다운로드됨 (이 파일을 안전하게 보관!)

### 5단계: Google 스프레드시트 생성

1. [Google Sheets](https://sheets.google.com/) 접속
2. 새 스프레드시트 생성
3. 이름 지정 (예: `FIRE25 Portfolio`)
4. **공유** 버튼 클릭
5. 서비스 계정 이메일 추가 (JSON 파일의 `client_email` 값)
   - 예: `fire25-sheets@your-project.iam.gserviceaccount.com`
6. **편집자** 권한 부여

### 6단계: Streamlit Secrets 설정

#### 로컬 실행 시:
`.streamlit/secrets.toml` 파일 생성:

```toml
spreadsheet_url = "https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

#### Streamlit Cloud 배포 시:
1. Streamlit Cloud 대시보드 → 앱 설정 → **Secrets**
2. 위와 동일한 내용 입력

---

## 📁 폴더 구조

```
fire25-dashboard/
├── fire25_v2_0.py          # 메인 앱
├── requirements.txt         # 의존성
├── .streamlit/
│   └── secrets.toml        # 시크릿 (로컬용, .gitignore에 추가)
└── GOOGLE_SHEETS_SETUP.md  # 이 가이드
```

---

## 📦 requirements.txt

```
streamlit
yfinance
pandas
gspread
google-auth
pytz
requests
```

---

## ✅ 테스트

1. 앱 실행: `streamlit run fire25_v2_0.py`
2. 사이드바에 "☁️ Google Sheets 연동됨" 표시 확인
3. 포트폴리오 입력 후 **💾 저장** 버튼 클릭
4. Google Sheets에서 데이터 저장 확인

---

## 🔐 보안 주의사항

1. **JSON 키 파일**: 절대 GitHub에 업로드하지 마세요!
2. **secrets.toml**: `.gitignore`에 추가하세요
3. **스프레드시트**: 서비스 계정에만 공유 (다른 사람에게 공개 X)

---

## 🆘 문제 해결

### "Google Sheets 연동이 설정되지 않았습니다"
→ `secrets.toml` 파일이 없거나 `gcp_service_account` 섹션이 없음

### "스프레드시트 URL이 설정되지 않았습니다"
→ `spreadsheet_url` 값이 없음

### "Portfolio 시트를 찾을 수 없습니다"
→ 첫 저장 시 자동 생성됨, 권한 문제일 수 있음

### 권한 오류
→ 서비스 계정 이메일이 스프레드시트에 **편집자**로 추가되었는지 확인

---

## 📊 저장되는 데이터

| 컬럼 | 설명 |
|------|------|
| Date | 저장 일시 (KST) |
| QQQM | QQQM 보유 수량 |
| SCHD | SCHD 보유 수량 |
| IAU | IAU 보유 수량 |
| SGOV | SGOV 보유 수량 |
| Cash | 예수금 (USD) |
| NewCash | 신규 자금 (USD) |
| TotalValue | 총 자산 가치 (USD) |

---

## 🎉 완료!

이제 어디서든 포트폴리오를 저장하고 불러올 수 있습니다!
