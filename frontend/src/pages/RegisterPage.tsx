import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate } from 'react-router-dom';
import { login, register as registerUser } from '@/api/auth';
import { useAuth } from '@/stores/auth';

interface Form { username: string; password: string }

export default function RegisterPage() {
  const { register, handleSubmit } = useForm<Form>();
  const setToken = useAuth((s) => s.setToken);
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(values: Form) {
    setError(null);
    try {
      await registerUser(values.username, values.password);
      const { access_token } = await login(values.username, values.password);
      setToken(access_token);
      navigate('/projects');
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Registration failed');
    }
  }

  return (
    <div className="min-h-full grid place-items-center p-6">
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="w-full max-w-sm bg-white p-6 rounded-lg shadow space-y-4"
      >
        <h1 className="text-2xl font-semibold">Create account</h1>
        <input
          {...register('username', { required: true, minLength: 3 })}
          autoComplete="username"
          placeholder="Username (3+ chars, A-Z 0-9 _ . -)"
          className="w-full border rounded px-3 py-2"
        />
        <input
          {...register('password', { required: true, minLength: 4 })}
          type="password"
          autoComplete="new-password"
          placeholder="Password (4+ chars)"
          className="w-full border rounded px-3 py-2"
        />
        {error && <p className="text-red-600 text-sm">{error}</p>}
        <button className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700">
          Register
        </button>
        <p className="text-sm text-slate-600">
          Already have an account? <Link to="/login" className="text-blue-600">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
