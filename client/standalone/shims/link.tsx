// Standalone shim for `next/link`: the standalone player has no router, so a
// plain <a> is enough. Only `href`/`children` matter here; Next-specific props
// (prefetch, replace, scroll, …) are accepted and ignored.
import React from "react";

type LinkProps = {
  href?: string | { pathname?: string };
  children?: React.ReactNode;
  prefetch?: boolean;
  replace?: boolean;
  scroll?: boolean;
} & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

const Link = React.forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  { href, children, prefetch, replace, scroll, ...rest },
  ref,
) {
  void prefetch;
  void replace;
  void scroll;
  const url = typeof href === "string" ? href : href?.pathname ?? "#";
  return (
    <a ref={ref} href={url} {...rest}>
      {children}
    </a>
  );
});

export default Link;
