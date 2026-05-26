"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeSanitize from "rehype-sanitize";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface MarkdownRendererProps {
  content: string;
  fontSize?: number;
  compact?: boolean;
}

export function MarkdownRenderer({
  content,
  fontSize = 13,
  compact = false,
}: MarkdownRendererProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const gap = compact ? "0 0 6px" : "0 0 12px";

  return (
    <div
      className={dark ? "md-dark" : "md-light"}
      style={{
        color: t.text,
        fontSize,
        lineHeight: 1.65,
        wordBreak: "break-word",
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize, rehypeHighlight]}
        components={{
          h1: ({ children }) => (
            <h1
              style={{
                fontSize: fontSize * 1.6,
                fontWeight: 700,
                color: t.text,
                margin: compact ? "8px 0 5px" : "18px 0 10px",
                lineHeight: 1.3,
                borderBottom: `1px solid ${t.border}`,
                paddingBottom: 6,
              }}
            >
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2
              style={{
                fontSize: fontSize * 1.35,
                fontWeight: 700,
                color: t.text,
                margin: compact ? "7px 0 4px" : "16px 0 8px",
                lineHeight: 1.3,
              }}
            >
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3
              style={{
                fontSize: fontSize * 1.15,
                fontWeight: 600,
                color: t.text,
                margin: compact ? "6px 0 3px" : "14px 0 6px",
                lineHeight: 1.3,
              }}
            >
              {children}
            </h3>
          ),
          h4: ({ children }) => (
            <h4
              style={{
                fontSize: fontSize * 1.05,
                fontWeight: 600,
                color: t.textSub,
                margin: compact ? "5px 0 2px" : "12px 0 4px",
              }}
            >
              {children}
            </h4>
          ),
          h5: ({ children }) => (
            <h5
              style={{
                fontSize,
                fontWeight: 600,
                color: t.textSub,
                margin: compact ? "4px 0 2px" : "10px 0 4px",
              }}
            >
              {children}
            </h5>
          ),
          h6: ({ children }) => (
            <h6
              style={{
                fontSize: fontSize * 0.9,
                fontWeight: 600,
                color: t.textDim,
                margin: compact ? "4px 0 2px" : "10px 0 4px",
              }}
            >
              {children}
            </h6>
          ),
          p: ({ children }) => (
            <p style={{ margin: gap, lineHeight: 1.65, color: t.text }}>
              {children}
            </p>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: dark ? "#7A7ACC" : "#4444AA",
                textDecoration: "underline",
                textUnderlineOffset: 2,
                transition: "opacity 0.15s",
              }}
            >
              {children}
            </a>
          ),
          strong: ({ children }) => (
            <strong style={{ fontWeight: 700, color: t.text }}>
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em style={{ fontStyle: "italic", color: t.textSub }}>
              {children}
            </em>
          ),
          del: ({ children }) => (
            <del style={{ textDecoration: "line-through", color: t.textDim }}>
              {children}
            </del>
          ),
          code: ({ className, children, ...props }) => {
            const isBlock = Boolean(className);
            if (!isBlock) {
              return (
                <code
                  style={{
                    background: dark
                      ? "rgba(255,255,255,0.09)"
                      : "rgba(0,0,0,0.07)",
                    border: `1px solid ${t.border}`,
                    borderRadius: 4,
                    padding: "1px 6px",
                    fontSize: fontSize * 0.88,
                    fontFamily:
                      "var(--font-jetbrains-mono), 'JetBrains Mono', monospace",
                    color: dark ? "#e06c75" : "#c0392b",
                  }}
                >
                  {children}
                </code>
              );
            }
            return (
              <code
                className={className}
                style={{
                  fontFamily:
                    "var(--font-jetbrains-mono), 'JetBrains Mono', monospace",
                  fontSize: fontSize * 0.88,
                  lineHeight: 1.55,
                }}
                {...props}
              >
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre
              style={{
                background: dark
                  ? "rgba(13,17,23,0.95)"
                  : "rgba(246,248,250,0.98)",
                border: `1px solid ${t.border}`,
                borderRadius: 8,
                padding: "12px 16px",
                overflowX: "auto",
                margin: compact ? "4px 0 8px" : "6px 0 14px",
                lineHeight: 1.55,
                fontFamily:
                  "var(--font-jetbrains-mono), 'JetBrains Mono', monospace",
              }}
            >
              {children}
            </pre>
          ),
          ul: ({ children }) => (
            <ul
              style={{
                paddingLeft: 20,
                margin: compact ? "2px 0 5px" : "4px 0 10px",
                listStyleType: "disc",
              }}
            >
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol
              style={{
                paddingLeft: 20,
                margin: compact ? "2px 0 5px" : "4px 0 10px",
                listStyleType: "decimal",
              }}
            >
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li style={{ margin: "2px 0", color: t.text, lineHeight: 1.55 }}>
              {children}
            </li>
          ),
          input: ({ checked, ...props }) => (
            <input
              type="checkbox"
              checked={Boolean(checked)}
              readOnly
              style={{
                marginRight: 6,
                accentColor: "#8B1A2F",
                cursor: "default",
              }}
              {...props}
            />
          ),
          blockquote: ({ children }) => (
            <blockquote
              style={{
                borderLeft: `3px solid ${
                  dark ? "rgba(139,26,47,0.6)" : "rgba(139,26,47,0.45)"
                }`,
                paddingLeft: 12,
                paddingTop: 6,
                paddingBottom: 6,
                margin: compact ? "4px 0 6px" : "8px 0 14px",
                color: t.textSub,
                background: dark
                  ? "rgba(139,26,47,0.04)"
                  : "rgba(139,26,47,0.03)",
                borderRadius: "0 4px 4px 0",
              }}
            >
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div
              style={{
                overflowX: "auto",
                margin: compact ? "4px 0 8px" : "8px 0 14px",
                borderRadius: 6,
                border: `1px solid ${t.border}`,
              }}
            >
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: fontSize * 0.93,
                }}
              >
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead
              style={{
                background: dark
                  ? "rgba(255,255,255,0.05)"
                  : "rgba(0,0,0,0.04)",
              }}
            >
              {children}
            </thead>
          ),
          tr: ({ children }) => (
            <tr style={{ borderBottom: `1px solid ${t.border}` }}>
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th
              style={{
                padding: "7px 12px",
                textAlign: "left",
                fontWeight: 700,
                color: t.text,
                borderRight: `1px solid ${t.border}`,
                fontSize: fontSize * 0.9,
                whiteSpace: "nowrap",
              }}
            >
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td
              style={{
                padding: "5px 12px",
                color: t.textSub,
                borderRight: `1px solid ${t.border}`,
              }}
            >
              {children}
            </td>
          ),
          hr: () => (
            <hr
              style={{
                border: "none",
                borderTop: `1px solid ${t.border}`,
                margin: compact ? "8px 0" : "16px 0",
              }}
            />
          ),
          img: ({ src, alt }) => (
            // Markdown can reference arbitrary external image URLs; next/image
            // would need per-domain remotePatterns (unknowable for user content)
            // and sharp, which is disabled in this deployment. A plain <img> is
            // the correct choice here.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={src}
              alt={alt ?? ""}
              style={{
                maxWidth: "100%",
                borderRadius: 6,
                margin: "4px 0",
                display: "block",
              }}
              loading="lazy"
            />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
