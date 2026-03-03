import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { HomePage, StylesPage, MaterialsPage, ReviewsPage, CoversPage } from './pages';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/styles" element={<StylesPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/reviews" element={<ReviewsPage />} />
        <Route path="/covers" element={<CoversPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
