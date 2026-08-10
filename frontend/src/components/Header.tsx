import { useEffect, useState } from "react";

interface HeaderProps {
  title: string;
}

export function Header({ title }: HeaderProps) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <header className="header">
      <h1 className="header-title">{title}</h1>
      <span className="header-clock">{now.toLocaleTimeString("en-US", { hour12: false })}</span>
    </header>
  );
}
