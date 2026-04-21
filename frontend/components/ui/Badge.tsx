// components/ui/Badge.tsx — trading-style inline badge
import React from 'react';

export type BadgeVariant = 'up' | 'down' | 'accent' | 'info' | 'neutral';

interface Props {
    variant?: BadgeVariant;
    children: React.ReactNode;
    className?: string;
}

export default function Badge({ variant = 'neutral', children, className = '' }: Props) {
    return (
        <span className={`badge ${variant} ${className}`.trim()}>
            {children}
        </span>
    );
}
