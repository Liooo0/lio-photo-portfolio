const gallery = document.getElementById("gallery-grid");

// 这里写相对路径（相对于 index.html）
const images = [
  "images/star/star01.jpg",
  "images/star/star02.jpg",
  "images/star/star03.jpg",
];

images.forEach(file => {
  const img = document.createElement("img");
  img.src = file;
  img.alt = "摄影作品";
  gallery.appendChild(img);
});
