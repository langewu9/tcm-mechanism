@echo off
cd /d D:\MMDD\tcm_pharmacology_platform
set DATABASE_URL=file:./dev.db
set AUTH_SECRET=local-dev-qihuang-change-me
npm --cache .\.npm-cache run dev
