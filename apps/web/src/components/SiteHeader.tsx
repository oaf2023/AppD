"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Messages } from "@/i18n/messages";
import { BrandMark } from "@/features/brand";
import { buttonClasses } from "@/components/ui";

type SiteHeaderProps = {
  messages: Messages;
  isAuthenticated: boolean;
};

/**
 * Cabecera responsive: en móvil colapsa la navegación tras un botón con
 * `aria-expanded`; el enlace de la página actual lleva `aria-current="page"`.
 */
export function SiteHeader({ messages, isAuthenticated }: SiteHeaderProps): React.JSX.Element {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const links = isAuthenticated
    ? [
        { href: "/", label: messages.nav.home },
        { href: "/#mercados", label: messages.nav.markets },
        { href: "/panel", label: messages.nav.panel },
      ]
    : [
        { href: "/", label: messages.nav.home },
        { href: "/#mercados", label: messages.nav.markets },
        { href: "/login", label: messages.nav.access },
      ];

  function isCurrent(href: string): boolean {
    return pathname === href;
  }

  return (
    <header className="border-b border-ink-soft bg-ink text-white">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-6 py-4">
        <Link href="/" className="flex items-center gap-3 rounded" aria-label={messages.brand.projectName}>
          <BrandMark className="h-9 w-9" />
          <span className="flex flex-col">
            <strong className="text-lg leading-tight">{messages.brand.projectName}</strong>
            <small className="text-sm text-brand-300">{messages.brand.tagline}</small>
          </span>
        </Link>

        <nav aria-label={messages.nav.mainLabel} className="hidden items-center gap-2 md:flex">
          {links.map((link) =>
            link.href === "/login" && !isAuthenticated ? (
              <Link
                key={link.href}
                href={link.href}
                aria-current={isCurrent(link.href) ? "page" : undefined}
                className={buttonClasses("primary", "sm")}
              >
                {link.label}
              </Link>
            ) : (
              <Link
                key={link.href}
                href={link.href}
                aria-current={isCurrent(link.href) ? "page" : undefined}
                className="rounded px-3 py-2 text-sm text-white hover:bg-ink-soft aria-[current=page]:bg-ink-soft aria-[current=page]:font-semibold"
              >
                {link.label}
              </Link>
            ),
          )}
        </nav>

        <button
          type="button"
          className="rounded px-3 py-2 text-sm font-semibold text-white hover:bg-ink-soft md:hidden"
          aria-expanded={open}
          aria-controls="menu-movil"
          aria-label={open ? messages.nav.menuClose : messages.nav.menuOpen}
          onClick={() => setOpen((value) => !value)}
        >
          {messages.nav.menuLabel}
        </button>
      </div>

      {open ? (
        <nav aria-label={messages.nav.mainLabel} id="menu-movil" className="border-t border-ink-soft md:hidden">
          <ul className="mx-auto flex w-full max-w-5xl flex-col gap-1 px-6 py-3">
            {links.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={isCurrent(link.href) ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  className="block rounded px-3 py-2.5 text-sm text-white hover:bg-ink-soft aria-[current=page]:bg-ink-soft aria-[current=page]:font-semibold"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </header>
  );
}
