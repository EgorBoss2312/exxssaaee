import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import Layout from "./Layout";
import Chat from "./pages/Chat";
import Knowledge from "./pages/Knowledge";
import Login from "./pages/Login";
import Admin from "./pages/Admin";
import Upload from "./pages/Upload";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Chat />} />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/upload" element={<Upload />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
