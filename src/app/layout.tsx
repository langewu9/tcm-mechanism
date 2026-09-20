import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import "./product.css";

export const metadata: Metadata = {
  title: {
    default: "远志 AI Scientist",
    template: "%s | 远志 AI Scientist"
  },
  description: "面向中医药网络药理学研究的疾病、中药、成分、靶点、通路与医案一体化智能分析平台"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <Script id="strip-extension-hydration-attributes" strategy="beforeInteractive">
          {`(() => {
            const attribute = "data-sg-checked";
            const strip = (node) => {
              if (!(node instanceof Element)) return;
              node.removeAttribute(attribute);
              node.querySelectorAll?.("[data-sg-checked]").forEach((element) => {
                element.removeAttribute(attribute);
              });
            };
            const observer = new MutationObserver((records) => {
              records.forEach((record) => {
                if (record.type === "attributes") strip(record.target);
                record.addedNodes.forEach(strip);
              });
            });
            observer.observe(document, {
              attributes: true,
              attributeFilter: [attribute],
              childList: true,
              subtree: true
            });
            document.addEventListener("DOMContentLoaded", () => {
              strip(document.documentElement);
              window.setTimeout(() => observer.disconnect(), 2000);
            }, { once: true });
          })();`}
        </Script>
        {children}
      </body>
    </html>
  );
}
