// 入口文件

import { createRoot } from "react-dom/client";
import App from "./App";

// 全局样式
const style = document.createElement("style");
style.textContent = `
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
  #root { min-height: 100vh; }
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-thumb { background: #d9d9d9; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #bfbfbf; }
`;
document.head.appendChild(style);

createRoot(document.getElementById("root")!).render(<App />);
