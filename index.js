// server/app.js
const cors = require('cors');
const express = require('express');
const mongoose = require('mongoose');
const compression = require('compression');
const dotenv = require('dotenv');
const passport = require('passport');
const session = require('express-session');
const helmet = require('helmet');

// ⚠️ If using connect-mongo v3:
const MongoStore = require('connect-mongo')(session);
// If using v4+, instead do:
// const MongoStore = require('connect-mongo');
// and use: store: MongoStore.create({ mongoUrl: process.env.MONGO_URI })

dotenv.config({ path: './config/config.env' });

const PORT = process.env.PORT || 3000;
const NODE_ENV = process.env.NODE_ENV || 'development';
const FRONTEND_DIR = __dirname + '/frontend/build';

const app = express();

// In Railway/behind proxies, trust the proxy so secure cookies work when on https
app.set('trust proxy', 1);

// DB
mongoose.connect(process.env.MONGO_URI, {
  useNewUrlParser: true,
  useUnifiedTopology: true,
});

// Passport
require('./config/passport')(passport);

// Core middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(compression());

// CORS (relax as needed; if serving frontend from same origin you can remove)
app.use(
  cors({
    origin: true,
    credentials: true,
  })
);

// 🔐 Helmet + CSP: allow Razorpay script/frames/connect
app.use(
  helmet({
    contentSecurityPolicy: {
      useDefaults: true,
      directives: {
        "default-src": ["'self'"],
        // allow tiny inline React runtime and WASM eval
        // note: some environments still require 'unsafe-eval' in addition to 'wasm-unsafe-eval'
        "script-src": [
          "'self'",
          "'unsafe-inline'",
          "'wasm-unsafe-eval'",
          "'unsafe-eval'",
          "https://checkout.razorpay.com",
          "https://cdn.jsdelivr.net",
          "https://fastly.jsdelivr.net"
        ],
        // ZXing wasm is fetched via XHR/fetch
        "connect-src": [
          "'self'",
          "https://api.razorpay.com",
          "https://checkout.razorpay.com",
          "https://cdn.jsdelivr.net",
          "https://fastly.jsdelivr.net"
        ],
        // the Razorpay frame + (optional) any other payment frames
        "frame-src": ["'self'", "https://*.razorpay.com"],
        "img-src": ["'self'", "data:", "https://*.razorpay.com"],
        "style-src": ["'self'", "'unsafe-inline'"],
        // let the QR lib play a short data: beep; also allow self-hosted files
        "media-src": ["'self'", "data:"],
        // if your QR lib spawns a worker (many wasm builds do)
        "worker-src": ["'self'", "blob:"]
      }
    },
    // you’re embedding third-party frames (Razorpay), so keep COEP off
    crossOriginEmbedderPolicy: false,
    // optional but recommended to silence referrer leakage
    referrerPolicy: { policy: "no-referrer" },
    // optional: explicitly declare camera permission scope
    // (older browsers ignore; harmless)
    permissionsPolicy: {
      features: {
        camera: ["self"],
        microphone: ["self"]
      }
    }
  })
);

// Sessions
app.use(
  session({
    secret: 'IIITL MESS PORTAL',
    resave: true,
    saveUninitialized: true,
    cookie: {
      // If your frontend is same-origin (served by this server), Lax is fine:
      sameSite: 'lax',
      // If frontend is on a different domain, use sameSite:'none' and secure:true
      secure: NODE_ENV === 'production', // relies on trust proxy for https
    },
    store:
      // v3 API:
      new MongoStore({ mongooseConnection: mongoose.connection }),
    // v4 API would be:
    // MongoStore.create({ mongoUrl: process.env.MONGO_URI }),
  })
);

app.use(passport.initialize());
app.use(passport.session());

// Auth gates
app.use('/api/admin/:all', (req, res, next) => {
  if (req.isAuthenticated() && req.user?.email === process.env.ADMIN) return next();
  return res.sendStatus(401);
});

app.use('/api/user/:all', (req, res, next) => {
  if (req.isAuthenticated()) return next();
  return res.sendStatus(401);
});

// Routes
app.use('/api/auth', require('./routes/auth'));
app.use('/api/data', require('./routes/data'));
app.use('/api/admin', require('./routes/admin'));
app.use('/api/user', require('./routes/user'));

// Static frontend
app.use(express.static(FRONTEND_DIR));
app.get('*', (req, res) => res.sendFile(FRONTEND_DIR + '/index.html'));

// Start
app.listen(PORT, () => {
  console.log(`Server started on port ${PORT} (${NODE_ENV})`);
});