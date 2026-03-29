// components/layout/Header.tsx
import Link from 'next/link';
import styles from './Header.module.css';

export default function Header() {
    return (
        <header className={styles.header}>
            <div className={`container ${styles.inner}`}>
                <Link href="/" className={styles.logo}>
                    <div className={styles.logoIcon}>🚗</div>
                    <div>
                        <div className={styles.logoText}>Avto Analytics</div>
                        <div className={styles.logoSub}>Казахстан</div>
                    </div>
                </Link>

                <nav className={styles.nav}>
                    <Link href="/" className={styles.navLink}>Дашборд</Link>
                </nav>

                <div className={styles.actions}>
                    <Link href="/pro" className={styles.proBadge}>⚡ PRO</Link>
                    <Link href="/auth/login" className="btn btn-ghost" style={{ fontSize: '13px', padding: '7px 14px' }}>
                        Войти
                    </Link>
                </div>
            </div>
        </header>
    );
}
