"use client";

import { FolderOpen, ListMusic, Piano, SlidersHorizontal } from "lucide-react";

export type MobileTab = "play" | "source" | "sound" | "library";

const TABS: { id: MobileTab; label: string; Icon: typeof Piano }[] = [
  { id: "play", label: "Putar", Icon: Piano },
  { id: "source", label: "Sumber", Icon: ListMusic },
  { id: "sound", label: "Suara", Icon: SlidersHorizontal },
  { id: "library", label: "Pustaka", Icon: FolderOpen },
];

interface Props {
  tab: MobileTab;
  onChange: (t: MobileTab) => void;
  /** small status dots: which tabs have something waiting */
  badges?: Partial<Record<MobileTab, "busy" | "ready">>;
}

export default function BottomTabs({ tab, onChange, badges }: Props) {
  return (
    <nav
      aria-label="Navigasi utama"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-cyan-500/20 bg-[#05060c]/95 backdrop-blur-md"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex max-w-[560px] items-stretch px-1">
        {TABS.map(({ id, label, Icon }) => {
          const active = tab === id;
          const badge = badges?.[id];
          return (
            <button
              key={id}
              type="button"
              onClick={() => onChange(id)}
              aria-current={active ? "page" : undefined}
              className={`relative flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition active:scale-95 ${
                active ? "text-cyan-200" : "text-slate-500"
              }`}
            >
              <span className="relative">
                <Icon size={19} />
                {badge && (
                  <span
                    className={`absolute -right-1.5 -top-1 h-2 w-2 rounded-full ${
                      badge === "busy"
                        ? "animate-pulse bg-pink-400 shadow-[0_0_8px_1px_rgba(255,0,200,0.9)]"
                        : "bg-emerald-400"
                    }`}
                  />
                )}
              </span>
              {label}
              {active && (
                <span className="absolute inset-x-4 top-0 h-0.5 rounded-full bg-gradient-to-r from-cyan-400 to-pink-500" />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
