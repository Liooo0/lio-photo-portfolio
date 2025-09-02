// 自动加载 /images/ 目录下的图片
const gallery = document.querySelector(".gallery-grid");

const images = [
  "photo1.jpg",
  "photo2.jpg",
  "photo3.jpg",
  "photo4.jpg",
];

images.forEach(file => {
  const div = document.createElement("div");
  div.className = "gallery-item";
  div.innerHTML = `<img src="images/${file}" alt="作品">`;
  gallery.appendChild(div);
});

