"use client";

import Link from "next/link";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import type { Citation } from "@/lib/types";

const components: Components = {
  a({ href, children }) {
    if (href && href.startsWith("/")) {
      return <Link href={href}>{children}</Link>;
    }
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
  table({ children }) {
    return (
      <div className="md-table-wrap">
        <table>{children}</table>
      </div>
    );
  },
};

/**
 * Render LLM-produced Markdown (tables, bold, lists, headings).
 *
 * remark-gfm provides GitHub-flavored tables; rehype-raw preserves literal
 * HTML like `<br>` inside cells; rehype-sanitize strips any unsafe HTML
 * (scripts, event handlers, javascript: URLs) since the content is
 * model-generated.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

/**
 * Turn inline `[C1]` markers into links that jump to the cited chunk,
 * e.g. `[C1](/meetings/{meeting_id}#chunk-{chunk_id})`.
 */
export function linkCitations(content: string, citations: Citation[]): string {
  let result = content;
  // Longest markers first so `[C1]` can never clobber a longer `[C12]`.
  const ordered = [...citations].sort((a, b) => b.marker.length - a.marker.length);
  for (const citation of ordered) {
    result = result.replaceAll(
      `[${citation.marker}]`,
      `[${citation.marker}](/meetings/${citation.meeting_id}#chunk-${citation.chunk_id})`,
    );
  }
  return result;
}
