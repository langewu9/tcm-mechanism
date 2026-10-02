import { Link } from "react-router-dom";
export function RegisterPage() {
  return <main className="site-home auth-page"><section className="auth-card panel">
    <Link className="auth-back" to="/">← 返回首页</Link><p className="page-kicker">Researcher account</p><h1 className="page-title">研究者账号</h1>
    <p className="page-description">当前版本尚未开放自助注册。为了确保上传数据与研究者身份可追溯，账号由平台管理员创建。</p>
    <Link className="btn btn-primary" to="/login">已有账号，前往登录</Link>
  </section></main>;
}
