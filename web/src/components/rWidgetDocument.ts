const WIDGET_POLICY = "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'";

export async function loadRWidgetDocument(url: string, signal: AbortSignal) {
  if (!/^\/(?:api\/v1\/research\/analysis-artifacts\/\d+\/download\/|r-(?:public-)?demo\/[a-z0-9_-]+\.html)(?:\?[^#]*)?$/.test(url)) {
    throw new Error("交互图表地址无效，请重新生成图表。");
  }
  const response = await fetch(url, { credentials: "same-origin", signal });
  if (!response.ok) throw new Error(`交互图表加载失败（HTTP ${response.status}），请重试或重新登录。`);
  if (!response.headers.get("Content-Type")?.toLowerCase().includes("text/html")) {
    throw new Error("交互图表返回格式不正确，请重新生成图表。");
  }
  const html = await response.text();
  if (!/<head(?:\s[^>]*)?>/i.test(html)) throw new Error("交互图表文件不完整，请重新生成图表。");
  // Fetch through the authenticated application request, then execute only in
  // an opaque iframe. srcdoc does not inherit the HTTP response's CSP, so put
  // our network-disabled policy before every widget dependency explicitly.
  return html.replace(/<head(?:\s[^>]*)?>/i, head => `${head}<meta http-equiv="Content-Security-Policy" content="${WIDGET_POLICY}">`);
}
