// components/ui/FilterDropdown.tsx — generic anchored portal dropdown for filter chips
import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';

interface Props {
    open: boolean;
    anchorRect: DOMRect | null;
    onClose: () => void;
    children: React.ReactNode;
    /** min width in px (default 240). Some dropdowns want wider. */
    minWidth?: number;
}

/**
 * Anchored dropdown rendered via portal to <body>, so the sticky FilterBar
 * can't clip it. Positions itself 4px below the anchor chip and left-aligns
 * to the chip. Closes on Escape key or click outside of the panel.
 *
 * The caller owns `open`. The parent is responsible for passing the chip's
 * DOMRect as `anchorRect` (capture via ref.getBoundingClientRect() on click).
 */
export default function FilterDropdown({
    open,
    anchorRect,
    onClose,
    children,
    minWidth = 240,
}: Props) {
    const panelRef = useRef<HTMLDivElement | null>(null);
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
    }, []);

    // Close on Escape.
    useEffect(() => {
        if (!open) return;
        function onKey(e: KeyboardEvent) {
            if (e.key === 'Escape') onClose();
        }
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [open, onClose]);

    // Close on outside-click (mousedown ensures we win race with child buttons).
    useEffect(() => {
        if (!open) return;
        function onDown(e: MouseEvent) {
            const el = panelRef.current;
            if (!el) return;
            if (e.target instanceof Node && el.contains(e.target)) return;
            onClose();
        }
        // Delay one tick so the click that opened us doesn't instantly close.
        const t = window.setTimeout(() => {
            window.addEventListener('mousedown', onDown);
        }, 0);
        return () => {
            window.clearTimeout(t);
            window.removeEventListener('mousedown', onDown);
        };
    }, [open, onClose]);

    if (!mounted || !open || !anchorRect) return null;

    // Position: 4px below anchor, left-aligned. Clamp to viewport on the right.
    const top = anchorRect.bottom + 4;
    let left = anchorRect.left;
    if (typeof window !== 'undefined') {
        const viewportW = window.innerWidth;
        const est = Math.max(minWidth, anchorRect.width);
        if (left + est > viewportW - 8) {
            left = Math.max(8, viewportW - est - 8);
        }
    }

    const panel = (
        <div
            ref={panelRef}
            className="filter-dropdown"
            role="dialog"
            style={{
                position: 'fixed',
                top,
                left,
                minWidth,
                zIndex: 200,
            }}
        >
            {children}
        </div>
    );

    return ReactDOM.createPortal(panel, document.body);
}
