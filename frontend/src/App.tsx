import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { HomePage, StylesPage, MaterialsPage, ReviewsPage, CoversPage, GithubTrendsPage } from './pages';

const LayoutPage = lazy(() =>
  import('./pages/LayoutPage').then((mod) => ({ default: mod.LayoutPage })),
);

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/styles" element={<StylesPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/reviews" element={<ReviewsPage />} />
        <Route path="/covers" element={<CoversPage />} />
        <Route path="/github-trends" element={<GithubTrendsPage />} />
        <Route
          path="/layout"
          element={
            <Suspense fallback={<div style={{ padding: 24 }}>Loading layout...</div>}>
              <LayoutPage />
            </Suspense>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
