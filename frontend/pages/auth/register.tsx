// pages/auth/register.tsx
import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import Head from 'next/head';
import { authApi } from '@/lib/api';
import styles from './auth.module.css';

export default function RegisterPage() {
    const router = useRouter();
    const [fullName, setFullName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        if (password.length < 8) {
            setError('Пароль должен содержать минимум 8 символов');
            return;
        }
        setLoading(true);
        try {
            const data = await authApi.register({ email, password, full_name: fullName });
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
            router.push('/');
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Ошибка регистрации. Попробуйте снова.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <>
            <Head>
                <title>Регистрация — Avto Analytics KZ</title>
            </Head>
            <div className={styles.page}>
                <div className={styles.card}>
                    <div className={styles.logoWrap}>
                        <div className={styles.logoIcon}>🚗</div>
                        <div className={styles.logoText}>Avto Analytics</div>
                        <div className={styles.logoSub}>Казахстан</div>
                    </div>

                    <h1 className={styles.title}>Создать аккаунт</h1>
                    <p className={styles.sub}>Получите доступ к аналитике авторынка бесплатно</p>

                    <form onSubmit={handleSubmit} className={styles.form}>
                        <div className={styles.group}>
                            <label className={styles.label}>Имя</label>
                            <input
                                id="input-fullname"
                                type="text"
                                className={styles.input}
                                placeholder="Иван Иванов"
                                value={fullName}
                                onChange={(e) => setFullName(e.target.value)}
                                autoComplete="name"
                            />
                        </div>
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
                                placeholder="Минимум 8 символов"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                autoComplete="new-password"
                            />
                        </div>

                        {error && <div className={styles.error}>{error}</div>}

                        <button
                            id="btn-register"
                            type="submit"
                            className={`btn btn-primary ${styles.submit}`}
                            disabled={loading}
                        >
                            {loading ? 'Создаём аккаунт...' : 'Зарегистрироваться'}
                        </button>
                    </form>

                    {/* Plans overview */}
                    <div className={styles.plans}>
                        <div className={styles.plan}>
                            <div className={styles.planName}>Free</div>
                            <div className={styles.planDesc}>Графики за 30 дней, базовые фильтры</div>
                            <div className={styles.planPrice}>Бесплатно</div>
                        </div>
                        <div className={`${styles.plan} ${styles.planPro}`}>
                            <div className={styles.planName}>PRO ⚡</div>
                            <div className={styles.planDesc}>Из история за год, рентабельность, экспорт</div>
                            <div className={styles.planPrice}>4 990 ₸/мес</div>
                        </div>
                    </div>

                    <div className={styles.footer}>
                        Уже есть аккаунт?{' '}
                        <Link href="/auth/login" className={styles.link}>Войти</Link>
                    </div>
                </div>
            </div>
        </>
    );
}
