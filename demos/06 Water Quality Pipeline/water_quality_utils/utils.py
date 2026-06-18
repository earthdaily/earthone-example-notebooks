import earthdaily.earthone as eo
from earthdaily.earthone.catalog import Image, Product, GenericBand, SpectralBand, properties as p
import os
import numpy as np
from datetime import datetime, timedelta
import geopandas as gpd

auth = eo.auth.Auth().get_default_auth()
user_hash = auth.namespace
org = auth.payload['org']
run_id =   user_hash + ":" + datetime.utcnow().strftime("%Y%m%d")

def create_ndti_product(pid, name):
    """
    Creates a baseline catalog product
    """
    
    existing = Product.get(f"{org}:{pid}")
    if existing:
        status = existing.delete_related_objects()
        if status:
            import time
            status.wait_for_completion()
            time.sleep(5)
        existing.delete()

    product = Product.get_or_create(pid)
    product.name = name
    product.tags = ["water-quality-examples"]
    product.save()

    band = GenericBand(
        name="ndti",
        product=product,
        band_index=0,
        file_index=0,
        data_type="Float32",
        nodata=None,
        data_range = (-1,1),
        display_range=(-1,1),
        resolution={"unit":"meters", "value":10.}
    )
    band.save()

    return product


def create_s2_surrogate(pid, name, geojson_fpath, s2_sample_dates):
    
    existing = Product.get(f"{org}:{pid}")
    if existing:
        status = existing.delete_related_objects()
        if status:
            import time
            status.wait_for_completion()
            time.sleep(5)
        existing.delete()

    product = Product.get_or_create(pid)
    product.name = name
    product.tags = ["water-quality-examples"]
    product.save()

    nir = SpectralBand(
        name = "nir",
        product=product,
        band_index=0,
        file_index=0,
        data_type="Float32",
        nodata=None,
        data_range=(0,1),
        display_range=(0,0.4),
        resolution={"unit":"meters", "value":10.}
    )
    nir.save()
    red = SpectralBand(
        name="red",
        product=product,
        band_index=1,
        file_index=0,
        data_type="Float32",
        nodata=None,
        data_range=(0,1),
        display_range=(0,0.4),
        resolution={"unit":"meters", "value":10.}
    )
    red.save()
    green = SpectralBand(
        name="green", 
        product=product,
        band_index=2,
        file_index=0,
        data_type="Float32",
        nodata=None,
        data_range=(0,1),
        display_range=(0,0.4),
        resolution={"unit":"meters", "value": 10.}
    )
    green.save()

    scl = GenericBand(
        name="scl", 
        product=product,
        band_index=0,
        file_index=1,
        data_type="Byte", 
        nodata=0,
        data_range=(0,11),
        display_range=(0,11),
        resolution={"unit":"meters", "value": 10.}
    )
    scl.save()
    print(f"Created surrogate product {product.id}")
    
    gdf = gpd.read_file(geojson_fpath)
    utm_epsg = utm_epsg_from_centroid(gdf.iloc[0]['geometry'])
    
    aoi = eo.geo.AOI(
        geometry=gdf.iloc[0]['geometry'],
        crs=f"EPSG:{utm_epsg}"
    )

    s2_prod = Product.get("esa:sentinel-2:l2a:c1:v1")
    int_images = s2_prod.images().intersects(aoi)
    
    print("Downloading sample images to interactively upload...")

    img_fp_list = []

    for s2_date in s2_sample_dates:
        print(s2_date)
        s2_end_date = datetime.strptime(s2_date, "%Y-%m-%d")+timedelta(days=1)
        ic = int_images.filter(s2_date<p.acquired<s2_end_date).collect()
        if len(ic)==0:
            print(f"No images {s2_date}")
            continue
        ic.download_mosaic(["nir", "red", "green"], dest=f"data/{s2_date}.tif")
        ic.download_mosaic(["scl"], dest=f"data/{s2_date}-scl.tif")
        img_fp_list.append(f"data/{s2_date}.tif")
        
        print(f"Downloaded {s2_date}")
    
    image = Image(
        name=f"{s2_sample_dates[0]}",
        product=product,
        acquired=s2_sample_dates[0]
    )
    upload = image.upload(
        [img_fp_list[0], img_fp_list[0].replace(".tif", "-scl.tif")],
        overwrite=True,
    )
    upload.wait_for_completion()
    os.remove(img_fp_list[0])
    os.remove(img_fp_list[0].replace(".tif", "-scl.tif"))
    
    print(f"Uploaded initial sample image")
    
    return product

def utm_epsg_from_centroid(geom):
    c = geom.centroid
    lon, lat = c.x, c.y
    zone = int((lon + 180) // 6) + 1          # 1–60
    return (32600 if lat >= 0 else 32700) + zone

def apply_cloud_mask(stack, scl):
    """
    Masks cloud, cloud shadow, cirrus, saturated/defective, and no-data
    pixels using the Sentinel-2 L2A SCL band. Returns a NaN-filled,
    float32 copy of the stack ready for index computation.

    stack: shape (..., n_bands, y, x) — e.g. (10, 3, y, x) for a baseline
           stack, or (3, y, x) for a single target scene
    scl:   shape (..., y, x) — matching leading dims, no band axis
           e.g. (10, y, x) or (y, x)
    """
    invalid_classes = {0, 1, 3, 8, 9, 10}
    invalid = np.isin(scl, list(invalid_classes))   # shape matches scl

    # Insert a band axis so the mask broadcasts against stack's band dimension
    invalid_broadcast = invalid[..., np.newaxis, :, :] if stack.ndim == invalid.ndim + 1 else invalid

    stack_masked = np.where(invalid_broadcast, np.nan, stack).astype("float32")
    return stack_masked

    





    
    