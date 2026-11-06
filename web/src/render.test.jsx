import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import { StaticRouter, Routes, Route } from "react-router-dom";
import BlogPost from "./pages/BlogPost.jsx";
import { PostsProvider } from "./posts/context.jsx";

const body = 'hello <script>alert(1)</script> <img src=x onerror="alert(2)"> [x](javascript:alert(1)) ![i](http://insecure/x.png)';
const post = { slug: "p", title: "P", description: "d", date: "2026-01-01", tag: "T", body };

describe("BlogPost SSR", () => {
  const html = renderToString(
    <PostsProvider value={[post]}>
      <StaticRouter location="/blog/p"><Routes><Route path="/blog/:slug" element={<BlogPost />} /></Routes></StaticRouter>
    </PostsProvider>,
  );
  it("has no live script or handler from the body", () => {
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/<img[^>]*onerror/i);
    expect(html).not.toMatch(/href="javascript:/i);
    expect(html).not.toMatch(/src="http:/i);
  });
});
