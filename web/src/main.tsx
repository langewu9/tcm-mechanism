import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import "./styles/app.css";
import "./styles/legacy-global.css";
import "./styles/legacy-product.css";
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
