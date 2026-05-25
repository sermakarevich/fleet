import { useEffect, useRef, useState } from 'react';
import { Bar, BarChart } from 'recharts';

interface Props {
  value: number | null;
}

export function Sparkline({ value }: Props) {
  const [history, setHistory] = useState<number[]>([]);
  const prevRef = useRef<number | null>(null);

  useEffect(() => {
    if (value != null && value !== prevRef.current) {
      prevRef.current = value;
      setHistory(h => [...h, value].slice(-20));
    }
  }, [value]);

  if (history.length === 0) {
    return <span style={{ display: 'inline-block', width: 60, height: 20 }} />;
  }

  const data = history.map(v => ({ v }));
  return (
    <BarChart
      width={60}
      height={20}
      data={data}
      margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
    >
      <Bar dataKey="v" fill="#60a5fa" isAnimationActive={false} />
    </BarChart>
  );
}
