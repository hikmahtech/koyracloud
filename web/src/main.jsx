import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import Dashboard from "./App.jsx";
import Docs from "./pages/Docs.jsx";
import Blog from "./pages/Blog.jsx";
// Code-split: react-markdown only loads when a post page is opened, keeping it
// out of the landing/index bundle.
const BlogPost = lazy(() => import("./pages/BlogPost.jsx"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/docs" element={<Docs />} />
          <Route path="/blog" element={<Blog />} />
          <Route path="/blog/:slug" element={
            <Suspense fallback={<div className="grid-bg min-h-screen" />}><BlogPost /></Suspense>
          } />
          <Route path="/*" element={<Dashboard />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
