import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { login } from '@/api/auth';
import { useAuth } from '@/stores/auth';

interface Form { username: string; password: string }

export default function LoginPage() {
  const { register, handleSubmit } = useForm<Form>({
    defaultValues: { username: '', password: '' },
  });
  const setToken = useAuth((s) => s.setToken);
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(values: Form) {
    setError(null);
    try {
      const { access_token } = await login(values.username, values.password);
      setToken(access_token);
      navigate('/projects');
    } catch {
      setError('Invalid credentials');
    }
  }

  return (
    <div className="min-h-full grid place-items-center p-6">
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="w-full max-w-sm bg-white p-6 rounded-lg shadow space-y-4"
      >
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <input
          {...register('username', { required: true })}
          autoComplete="username"
          placeholder="Username"
          className="w-full border rounded px-3 py-2"
        />
        <input
          {...register('password', { required: true })}
          type="password"
          autoComplete="current-password"
          placeholder="Password"
          className="w-full border rounded px-3 py-2"
        />
        {error && <p className="text-red-600 text-sm">{error}</p>}
        <button className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700">
          Sign in
        </button>
      </form>
    </div>
  );
}
