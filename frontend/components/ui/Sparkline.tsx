// components/ui/Sparkline.tsx — pure SVG sparkline, optional area fill
import React from 'react';

interface Point { value: number }

interface Props {
    data: Point[];
    width?: number;
    height?: number;
    color?: string;
    fill?: boolean;
    strokeWidth?: number;
}

export default function Sparkline({
    data,
    width = 72,
    height = 32,
    color = 'var(--info)',
    fill = true,
    strokeWidth = 1.5,
}: Props) {
    if (!data || data.length < 2) return null;

    const values = data.map(d => d.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const stepX = width / (data.length - 1);

    const points = data.map((d, i) => {
        const x = i * stepX;
        const y = height - ((d.value - min) / range) * height;
        return [x, y] as const;
    });

    const linePath = points
        .map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`))
        .join(' ');
    const fillPath = `${linePath} L${width},${height} L0,${height} Z`;

    return (
        <svg
            className="sparkline"
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            aria-hidden
        >
            {fill && <path className="fill" d={fillPath} fill={color} />}
            <path className="line" d={linePath} stroke={color} strokeWidth={strokeWidth} />
        </svg>
    );
}
