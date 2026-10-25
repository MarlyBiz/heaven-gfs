# heaven-gfs
Every 3 h a GitHub Actions job pulls the 4-5 needed GFS 0.5° fields (byte ranges from the public `noaa-gfs-bdp-pds` S3 bucket),
encodes them as small PNG grids for f000-f072 every 3 h, adds NOAA WPC coded surface fronts, and publishes to GitHub Pages.
Format: see `gfs.py`. Data: NOAA GFS / NOAA WPC (public domain). Cost: free (public repo Actions + Pages).
