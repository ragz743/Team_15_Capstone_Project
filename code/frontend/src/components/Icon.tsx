type IconName = "plus" | "search" | "panel" | "refresh" | "arrow" | "chevron" | "thermometer" | "rain" | "wind" | "chat" | "close" | "warning";

const paths: Record<IconName, React.ReactNode> = {
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>,
  panel: <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16M5.5 8h1M5.5 11h1" /></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 7a7 7 0 0 1 11.5-1L20 9M4 15l2.4 3A7 7 0 0 0 17.9 17" /></>,
  arrow: <path d="M12 19V5m-6 6 6-6 6 6" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  thermometer: <><path d="M9 14.5V5a3 3 0 0 1 6 0v9.5a5 5 0 1 1-6 0Z" /><path d="M12 8v9" /><circle cx="12" cy="18" r="1" /></>,
  rain: <><path d="M7 15a4 4 0 1 1 .7-7.9A5 5 0 0 1 17 6a4.5 4.5 0 0 1 0 9" /><path d="m8 17-1 3m5-3-1 3m5-3-1 3" /></>,
  wind: <><path d="M3 8h12a3 3 0 1 0-3-3M3 12h16a2 2 0 1 1-2 2M3 16h7a3 3 0 1 1-3 3" /></>,
  chat: <path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-1 1V11.5a9 9 0 0 1 18 0Z" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  warning: <><path d="m10.3 4.4-8 14A1.7 1.7 0 0 0 3.8 21h16.4a1.7 1.7 0 0 0 1.5-2.6l-8-14a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4m0 4h.01" /></>,
};

export default function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  return <svg className={`icon ${className}`} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
