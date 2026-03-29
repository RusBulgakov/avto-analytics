// pages/auth/login.tsx
import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import Head from 'next/head';
import { authApi } from '@/lib/api';
import styles from './auth.module.css';

export default function LoginPage() {
    const router = useRouter();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            const data = await authApi.login(email, password);
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
            router.push('/');
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Неверный email или пароль');
        } finally {
            setLoading(false);
        }
    };

    return (
        <>
            <Head>
                <title>Вход — Avto Analytics KZ</title>
            </Head>
            <div className={styles.page}>
                <div className={styles.card}>
                    <div className={styles.logoWrap}>
                        <div className={styles.logoIcon}>🚗</div>
                        <div className={styles.logoText}>Avto Analytics</div>
                        <div className={styles.logoSub}>Казахстан</div>
                    </div>

                    <h1 className={styles.title}>Вход в аккаунт</h1>
                    <p className={styles.sub}>Войдите, чтобы получить доступ к аналитике</p>

                    <form onSubmit={handleSubmit} className={styles.form}>
                        <div className={styles.group}>
                            <label className={styles.label}>Email</label>
                            <input
                                id="input-email"
                                type="email"
                                className={styles.input}
                                placeholder="you@example.com"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                autoComplete="email"
                            />
                        </div>

                        <div className={styles.group}>
                            <label className={styles.label}>Пароль</label>
                            <input
                                id="input-password"
                                type="password"
                                className={styles.input}
                                placeholder="••••••••"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                autoComplete="current-password"
                            />
                        </div>

                        {error && <div className={styles.error}>{error}</div>}

                        <button
                            id="btn-login"
                            type="submit"
                            className={`btn btn-primary ${styles.submit}`}
                            disabled={loading}
                        >
                            {loading ? 'Входим...' : 'Войти'}
                        </button>
                    </form>

                    <div className={styles.footer}>
                        Нет аккаунта?{' '}
                        <Link href="/auth/register" className={styles.link}>
                            Зарегистрироваться
                        </Link>
                    </div>
                    <div className={styles.footer} style={{ marginTop: 8 }}>
                        <Link href="/" className={styles.link}>
                            ← Вернуться на дашборд
                        </Link>
                    </div>
                </div>
            </div>
        </>
    );
}
