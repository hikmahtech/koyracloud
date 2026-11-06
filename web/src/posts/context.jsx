import { createContext, useContext } from "react";
import { POSTS } from "./index.js";

// The merged post list, provided at SSR and hydration so both use the same data.
const PostsContext = createContext(POSTS);
export const PostsProvider = PostsContext.Provider;
export const usePosts = () => useContext(PostsContext);

// Client: read the list the prerenderer embedded (only present when Payload
// contributed); otherwise the file-only list is already the right one.
export function readEmbeddedPosts() {
  if (typeof document === "undefined") return POSTS;
  try {
    const el = document.getElementById("__POSTS__");
    return el ? JSON.parse(el.textContent) : POSTS;
  } catch {
    return POSTS;
  }
}
