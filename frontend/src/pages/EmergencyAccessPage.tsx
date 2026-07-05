import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { requestEmergencyCode, verifyEmergencyCode } from '@/api/auth';
import { useAuth } from '@/stores/auth';

export default function EmergencyAccessPage() {
  const setToken = useAuth((s) => s.setToken);
  const navigate = useNavigate();
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function sendCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { detail } = await requestEmergencyCode(email);
      setNotice(detail);
      setStep('code');
    } catch {
      setError('Could not send a code. Try again.');
    } finally {
      setLoading(false);
    }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { access_token } = await verifyEmergencyCode(email, code);
      setToken(access_token);
      navigate('/projects');
    } catch {
      setError('Invalid or expired code.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center bg-white px-6 py-10">
      <div className="w-full max-w-[340px]">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Emergency access</h1>
        <p className="mt-2 text-sm text-slate-500">
          Enter your admin email and we'll send a one-time code.
        </p>

        {step === 'email' ? (
          <form onSubmit={sendCode} className="mt-7 space-y-3">
            <input
              type="email"
              autoComplete="email"
              required
              aria-label="Admin email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
            />
            <button
              disabled={loading}
              className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:opacity-60"
            >
              {loading ? 'Sending…' : 'Send code'}
            </button>
          </form>
        ) : (
          <form onSubmit={submitCode} className="mt-7 space-y-3">
            {notice && <p className="text-sm text-slate-500">{notice}</p>}
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              aria-label="One-time code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="6-digit code"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm tracking-widest focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
            />
            <button
              disabled={loading}
              className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:opacity-60"
            >
              {loading ? 'Verifying…' : 'Verify'}
            </button>
          </form>
        )}

        {error && (
          <p className="mt-4 text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
