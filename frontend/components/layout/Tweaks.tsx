// components/layout/Tweaks.tsx — settings drawer (theme switcher for now)
import React from 'react';
import { useTheme, Theme } from '@/hooks/useTheme';

interface Props {
    open: boolean;
    onClose: () => void;
}

export default function Tweaks({ open, onClose }: Props) {
    const [theme, setTheme] = useTheme();

    return (
        <div className={`tweaks ${open ? 'open' : ''}`}>
            <div className="tweaks-h">
                <span>Настройки</span>
                <button className="tweaks-close" onClick={onClose} aria-label="Закрыть">
                    ×
                </button>
            </div>
            <div className="tweak-row">
                <div className="tweak-label">Тема</div>
                <div className="tweak-seg">
                    <button
                        className={theme === 'dark' ? 'active' : ''}
                        onClick={() => setTheme('dark' as Theme)}
                    >
                        Тёмная
                    </button>
                    <button
                        className={theme === 'light' ? 'active' : ''}
                        onClick={() => setTheme('light' as Theme)}
                    >
                        Светлая
                    </button>
                </div>
            </div>
        </div>
    );
}
