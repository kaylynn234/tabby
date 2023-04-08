import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import useTheme from "@mui/material/styles/useTheme";

export default function Home() {
  let theme = useTheme();

  return (
    <Grid container spacing={2} sx={{ height: '768px', paddingY: '144px' }}>
      <Grid
        item
        xs={12}
        md={6}
      >
        <Stack
          spacing={2}
          sx={{
            display: 'flex',
            height: '100%',
            alignItems: { xs: 'center', md: 'start' },
            justifyContent: 'center',
            textAlign: { xs: 'center', md: 'left' }
          }}
        >
          <Typography variant="h3" sx={{ fontWeight: 'bold' }}>
            A&nbsp;
            <Box
              sx={{
                display: 'inline',
                textDecorationThickness: '4px',
                textDecorationStyle: 'solid',
                textDecorationColor: 'primary.contrastText',
                textDecorationLine: 'underline',
                backgroundImage: 'linear-gradient(to right, #4392F1, #1170E4)',
                color: 'transparent',
                backgroundClip: 'text'
              }}
            >
              friendlier&nbsp;<wbr />
            </Box>
            Discord&nbsp;bot
          </Typography>
          <Typography variant="h6">
            Tabby stays out of your way so that you can focus on chatting<br />
          </Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <Button variant="contained" size="large">Dashboard</Button>
            <Button variant="outlined" size="large">Add to Discord</Button>
          </Stack>
        </Stack>
      </Grid>
      <Grid item xs={12} md={6} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <img src="/pusheen.png" style={{ maxWidth: '75%', maxHeight: '75%', objectFit: 'scale-down' }} />
      </Grid>
    </Grid>
  )
}
